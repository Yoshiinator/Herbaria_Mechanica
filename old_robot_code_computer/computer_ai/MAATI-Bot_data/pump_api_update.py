"""Arduino Gantry, Servo Arm & Pump Control API
FastAPI version
- Gantry: COM4 @ 115200
- Servo: COM3 @ 9600
- Pump: COM5 @ 9600
"""

import serial
import time
import threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="MATI Bot API")

gantry = None
servo = None
pump = None

# Track active pump timers
active_timers = {}

def init_serial(port, baudrate, name, retries=3):
    for attempt in range(retries):
        try:
            s = serial.Serial(port, baudrate, timeout=5)
            time.sleep(2)
            resp = s.readline().strip().decode('utf-8', errors='ignore')
            print(f"[{name}] Ready: {resp}")
            return s
        except Exception as e:
            print(f"[{name}] Attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return None

def send_command(ser, cmd, wait=True):
    if ser is None:
        return {"ok": False, "error": "Not connected"}
    try:
        ser.flushInput()
        ser.write((cmd + '\n').encode('utf-8'))
        if wait:
            resp = ser.readline().strip().decode('utf-8', errors='ignore')
            if resp.startswith('OK') or resp.startswith('ok'):
                return {"ok": True, "data": resp}
            elif resp.startswith('ERR'):
                return {"ok": False, "error": resp}
            return {"ok": True, "data": resp}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Models ──────────────────────────────────────────────────────────

class GantryMove(BaseModel):
    cmd: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    z: Optional[int] = None

class ServoSet(BaseModel):
    servo: int
    angle: int

class PumpSet(BaseModel):
    speed: int = 0

class PumpSetTime(BaseModel):
    """Pump set with time duration (in seconds)"""
    speed: int = 255
    time: int = 0  # Duration in seconds (0 = run until stopped)

# ── Gantry ──────────────────────────────────────────────────────────

@app.post("/api/gantry/move")
def gantry_move(data: GantryMove):
    if data.cmd:
        return send_command(gantry, data.cmd)
    cmd = ""
    if data.x is not None: cmd += f"x{data.x}"
    if data.y is not None: cmd += f"y{data.y}"
    if data.z is not None: cmd += f"z{data.z}"
    if not cmd:
        raise HTTPException(status_code=400, detail="Provide x, y, z or cmd")
    return send_command(gantry, cmd)

@app.get("/api/gantry/pos")
def gantry_pos():
    return send_command(gantry, 'pos')

@app.post("/api/gantry/reset")
def gantry_reset():
    return send_command(gantry, 'reset')

@app.post("/api/gantry/home")
def gantry_home():
    return send_command(gantry, 'home')

# ── Servo Arm ──────────────────────────────────────────────────────────
@app.post("/api/servo/set")
def servo_set(data: ServoSet):
    if data.servo < 1 or data.servo > 4:
        raise HTTPException(status_code=400, detail="Servo must be 1-4")
    if data.angle < 0 or data.angle > 180:
        raise HTTPException(status_code=400, detail="Angle must be 0-180")
    return send_command(servo, f"S{data.servo},{data.angle}")

@app.get("/api/servo/all")
def servo_all():
    return send_command(servo, 'A')

@app.post("/api/servo/reset")
def servo_reset():
    return send_command(servo, 'R')

@app.post("/api/arm/grip")
def arm_grip():
    return send_command(servo, 'S1,100')

@app.post("/api/arm/release")
def arm_release():
    return send_command(servo, 'S1,0')

# ── Pump Controller ──────────────────────────────────────────────────────────
def send_pump_cmd(cmd: str):
    if pump is None:
        return {"connected": False}
    try:
        pump.flushInput()
        pump.write((cmd + "\n").encode('utf-8'))
        time.sleep(0.15)
        resp = pump.readline().strip().decode('utf-8', errors='ignore')
        
        if resp.startswith('P') or resp.startswith('ALL'):
            parts = resp.split(':')
            if len(parts) == 2:
                prefix = parts[0]
                value = parts[1]
                if prefix == 'ALL':
                    speeds = [int(x) for x in value.split(',')]
                    return {"connected": True, "speeds": speeds}
                else:
                    pump_num = int(prefix[1])
                    speed = int(value)
                    return {"connected": True, "pump": pump_num, "speed": speed}
        if resp == 'ALL:OFF':
            return {"connected": True, "all_off": True}
        return {"connected": True, "raw": resp}
    except Exception as e:
        return {"connected": False, "error": str(e)}

def pump_timer_callback(pump_num):
    """Callback to turn off pump after timer expires"""
    print(f"Timer expired for pump {pump_num}, turning off...")
    send_pump_cmd(f"P{pump_num},0")
    if pump_num in active_timers:
        del active_timers[pump_num]

@app.post("/api/pump/{pump_num}/set")
def pump_set(pump_num: int, data: PumpSet):
    if pump_num < 1 or pump_num > 4:
        raise HTTPException(status_code=400, detail="Pump must be 1-4")
    if data.speed < 0 or data.speed > 255:
        raise HTTPException(status_code=400, detail="Speed must be 0-255")
    result = send_pump_cmd(f"P{pump_num},{data.speed}")
    if result.get("connected"):
        return {"ok": True, "pump": pump_num, "speed": data.speed}
    return result

@app.post("/api/pump/{pump_num}/set_time")
def pump_set_time(pump_num: int, data: PumpSetTime):
    """Set pump speed with optional time duration
    
    Body: {"speed": 255, "time": 10}
    - speed: 0-255 (default 255)
    - time: seconds to run (0 = run until stopped, max 3600)
    """
    if pump_num < 1 or pump_num > 4:
        raise HTTPException(status_code=400, detail="Pump must be 1-4")
    if data.speed < 0 or data.speed > 255:
        raise HTTPException(status_code=400, detail="Speed must be 0-255")
    if data.time < 0 or data.time > 3600:
        raise HTTPException(status_code=400, detail="Time must be 0-3600 seconds")
    
    # Cancel any existing timer for this pump
    if pump_num in active_timers:
        active_timers[pump_num].cancel()
        del active_timers[pump_num]
    
    # Set the pump speed
    result = send_pump_cmd(f"P{pump_num},{data.speed}")
    if not result.get("connected"):
        return result
    
    # If time > 0, set a timer to turn off
    if data.time > 0:
        timer = threading.Timer(data.time, pump_timer_callback, args=(pump_num,))
        timer.daemon = True
        active_timers[pump_num] = timer
        timer.start()
        return {
            "ok": True, 
            "pump": pump_num, 
            "speed": data.speed, 
            "time": data.time,
            "auto_off": True
        }
    
    return {
        "ok": True, 
        "pump": pump_num, 
        "speed": data.speed, 
        "time": data.time,
        "auto_off": False
    }

@app.post("/api/pump/{pump_num}/stop")
def pump_stop(pump_num: int):
    """Stop a pump (set speed to 0) and cancel any timer"""
    if pump_num < 1 or pump_num > 4:
        raise HTTPException(status_code=400, detail="Pump must be 1-4")
    
    # Cancel timer if exists
    if pump_num in active_timers:
        active_timers[pump_num].cancel()
        del active_timers[pump_num]
    
    return send_pump_cmd(f"P{pump_num},0")

@app.get("/api/pump/{pump_num}/status")
def pump_status(pump_num: int):
    if pump_num < 1 or pump_num > 4:
        raise HTTPException(status_code=400, detail="Pump must be 1-4")
    return send_pump_cmd(f"P{pump_num}?")

@app.get("/api/pump/all/status")
def pump_all_status():
    return send_pump_cmd("ALL?")

@app.post("/api/pump/all/off")
def pump_all_off():
    # Cancel all timers
    for pump_num in list(active_timers.keys()):
        active_timers[pump_num].cancel()
    active_timers.clear()
    
    return send_pump_cmd("OFF")

# ── Status ──────────────────────────────────────────────────────────
@app.get("/api/status")
def status():
    return {
        "gantry": gantry is not None and gantry.is_open,
        "servo": servo is not None and servo.is_open,
        "pump": pump is not None and pump.is_open
    }

@app.get("/api/health")
def health():
    all_ok = (gantry is not None and gantry.is_open) and (servo is not None and servo.is_open) and (pump is not None and pump.is_open)
    return {
        "ok": all_ok,
        "gantry": gantry is not None and gantry.is_open,
        "servo": servo is not None and servo.is_open,
        "pump": pump is not None and pump.is_open
    }

@app.get("/api/howto")
def howto():
    return {
        "title": "MATI Bot API",
        "version": "1.4",
        "port": 8000,
        "devices": {
            "gantry": {"port": "COM4", "baud": 115200},
            "servo": {"port": "COM3", "baud": 9600},
            "pump": {"port": "COM5", "baud": 9600}
        },
        "endpoints": {
            "POST /api/gantry/move": {"body": {"x": 10, "y": -5, "z": 20}},
            "GET /api/gantry/pos": {},
            "POST /api/gantry/home": {},
            "POST /api/servo/set": {"body": {"servo": 1, "angle": 90}},
            "GET /api/servo/all": {},
            "POST /api/arm/grip": {},
            "POST /api/arm/release": {},
            "POST /api/pump/<n>/set": {"body": {"speed": 128}},
            "POST /api/pump/<n>/set_time": {"body": {"speed": 255, "time": 10}},
            "POST /api/pump/<n>/stop": {},
            "GET /api/pump/<n>/status": {},
            "GET /api/pump/all/status": {},
            "POST /api/pump/all/off": {},
            "GET /api/health": {},
            "GET /api/howto": {}
        }
    }

# ── Startup ──────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    global gantry, servo, pump
    print("Connecting to Arduinos...")
    gantry = init_serial('COM4', 115200, "Gantry")
    servo = init_serial('COM3', 9600, "Servo")
    pump = init_serial('COM5', 9600, "Pump")
    
    if gantry and servo and pump:
        print("All devices connected!")
    else:
        print("Warning: Some devices failed")
        print(f"  Gantry: {'OK' if gantry else 'FAILED'}")
        print(f"  Servo: {'OK' if servo else 'FAILED'}")
        print(f"  Pump: {'OK' if pump else 'FAILED'}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)