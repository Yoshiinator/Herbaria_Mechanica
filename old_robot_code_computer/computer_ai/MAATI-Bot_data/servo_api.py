"""Servo & LED API Server - Arduino Mega on COM7
Separate server from main gantry API. Runs on port 8001.
Controls: LED on pin 13, Servos on pins 8,9,10,11
"""

import serial
import time
import threading
from flask import Flask, jsonify, request

app = Flask(__name__)

SERIAL_PORT = 'COM7'
BAUD = 9600
arduino = None
arduino_lock = threading.Lock()

def init_serial(port, baud):
    try:
        s = serial.Serial(port, baud, timeout=1)
        time.sleep(2)
        s.write(b'PING\r\n')
        resp = s.read(100)
        if b'PONG' in resp:
            print(f"[Arduino] Connected on {port}")
            return s
        print(f"[Arduino] {port} responded: {resp}")
        s.close()
        return None
    except Exception as e:
        print(f"[Arduino] Failed to open {port}: {e}")
        return None

def send_cmd(cmd):
    with arduino_lock:
        if not arduino or not arduino.is_open:
            return {"ok": False, "error": "Not connected"}
        try:
            arduino.write((cmd + "\r\n").encode())
            time.sleep(0.15)
            resp = arduino.read(200).decode().strip()
            return {"ok": True, "response": resp}
        except Exception as e:
            return {"ok": False, "error": str(e)}

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "connected": arduino is not None and arduino.is_open,
        "port": SERIAL_PORT
    })

# ---------- LED ----------
@app.route('/api/led/on', methods=['POST'])
def led_on():
    return jsonify(send_cmd("LEDON"))

@app.route('/api/led/off', methods=['POST'])
def led_off():
    return jsonify(send_cmd("LEDOFF"))

@app.route('/api/led/toggle', methods=['POST'])
def led_toggle():
    return jsonify(send_cmd("LEDTOGGLE"))

# ---------- SERVO ----------
@app.route('/api/servo/set', methods=['POST'])
def servo_set():
    data = request.get_json()
    servo_num = data.get('servo')
    angle = data.get('angle')
    if servo_num is None or angle is None:
        return jsonify({"ok": False, "error": "Provide servo (1-4) and angle (0-180)"}), 400
    return jsonify(send_cmd(f"S{servo_num},{angle}"))

@app.route('/api/servo/sweep', methods=['POST'])
def servo_sweep():
    return jsonify(send_cmd("SWEEP"))

@app.route('/api/servo/stop', methods=['POST'])
def servo_stop():
    return jsonify(send_cmd("STOP"))

@app.route('/api/servo/all', methods=['GET'])
def servo_all():
    return jsonify(send_cmd("A"))

@app.route('/api/arm/grip', methods=['POST'])
def arm_grip():
    return jsonify(send_cmd("G"))

@app.route('/api/arm/release', methods=['POST'])
def arm_release():
    return jsonify(send_cmd("L"))

if __name__ == '__main__':
    arduino = init_serial(SERIAL_PORT, BAUD)
    print(f"[Arduino] API ready on http://0.0.0.0:8001")
    app.run(host='0.0.0.0', port=8001, threaded=True)
