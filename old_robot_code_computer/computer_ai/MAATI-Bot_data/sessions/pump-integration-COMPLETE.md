# Pump Controller Integration - Complete Session

**Session ID:** 20260521_154703_6ea7987b
**Date:** 2026-05-21

---

## Overview

Complete integration of Arduino Mega 2560 on COM5 to control 4 water pumps.

---

## Step 1: Identify Arduino on NUC

```powershell
SSH to NUC → Get-PnpDevice -Class Ports
```

**Result:**
- COM3 - Arduino Mega 2560 (OK) → Servo arm
- COM4 - Arduino Mega 2560 (OK) → Gantry
- **COM5 - Arduino Mega 2560 (OK)** → **PUMP CONTROLLER**

---

## Step 2: Create Arduino Sketch

**File:** `pump_controller.ino`

**Pins:** 8, 9, 10, 11 (PWM for speed control)

**Commands:**
```
P<n>,<speed>  - Set pump n (1-4) speed (0-255)
P<n>?        - Query pump n status
ALL?         - Query all pumps
OFF           - Turn all pumps off
```

**Compile & Upload:**
```bash
arduino-cli compile -b arduino:avr:mega pump_controller.ino
arduino-cli upload -p COM5 -b arduino:avr:mega pump_controller.ino
```

**Success:** Sketch uploaded, uses 3724 bytes (1%)

---

## Step 3: Add Python API

**File:** `arduino_api_new.py`

```python
# Added global variable
pump = None

# Added pump_init in startup
pump = init_serial('COM5', 9600, 'Pump')

# Added endpoints
@app.route('/api/pump/<int:pump_num>/set', methods=['POST'])
@app.route('/api/pump/<int:pump_num>/status', methods=['GET'])
@app.route('/api/pump/all/status', methods=['GET'])
@app.route('/api/pump/all/off', methods=['POST'])
```

---

## Step 4: Deploy to NUC

```bash
# Copy to NUC
scp arduino_api_new.py mahim@192.168.1.2:C:/Users/mahim/

# Kill old API
taskkill /F /IM python.exe

# Start new API
Start-Process python -ArgumentList 'C:/Users/mahim/arduino_api_new.py'
```

**Result:** All devices connected!
- Servo COM3 @ 9600 baud ✓
- Gantry COM4 @ 115200 baud ✓
- **Pump COM5 @ 9600 baud ✓**

---

## Step 5: Test Each Pump

**Endpoint Base:** `http://192.168.1.2:8000`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pump/<n>/set` | POST | Set pump speed (0-255) |
| `/api/pump/<n>/status` | GET | Get pump n status |
| `/api/pump/all/status` | GET | Get all pumps |
| `/api/pump/all/off` | POST | Turn all off |

**Test Commands:**

```bash
# Pump 1 on at speed 200
curl -X POST http://192.168.1.2:8000/api/pump/1/set -H "Content-Type: application/json" -d '{"speed": 200}'

# Check all pumps
curl http://192.168.1.2:8000/api/pump/all/status

# Turn off all
curl -X POST http://192.168.1.2:8000/api/pump/all/off
```

**Expected Responses:**
- Set pump: `{"pump": 1, "speed": 200, "response": "P1:200"}`
- All status: `{"pumps": [200, 0, 0, 0]}`
- All off: `{"response": "ALL:OFF", "all_off": true}`

---

## Health Check

```bash
curl http://192.168.1.2:8000/api/health
```

**Response:** `{"gantry": true, "ok": true, "pump": true, "servo": true}`

---

## Full API Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/gantry/move` | POST | Move gantry (x, y, z) |
| `/api/gantry/pos` | GET | Get position |
| `/api/gantry/home` | POST | Go home |
| `/api/gantry/reset` | POST | Reset pos |
| `/api/gantry/status` | GET | Gantry status |
| `/api/servo/set` | POST | Set servo (1-4, angle) |
| `/api/servo/all` | GET | All servos |
| `/api/servo/reset` | POST | Reset servos |
| `/api/arm/grip` | POST | Gripper close |
| `/api/arm/release` | POST | Gripper open |
| `/api/pump/1/set` | POST | Pump 1 speed |
| `/api/pump/1/status` | GET | Pump 1 status |
| `/api/pump/all/status` | GET | All pumps |
| `/api/pump/all/off` | POST | All off |
| `/api/status` | GET | Quick status |
| `/api/health` | GET | Full health |
| `/api/howto` | GET | Documentation |

---

## Skill: mati-pump-control

Created skill with full documentation at: `~/.hermes/skills/robotics/mati-pump-control`

---

## Notes

- Arduino Mega 2560 on COM5 at 9600 baud
- 4 pumps on pins 8, 9, 10, 11
- PWM speed control 0-255
- API integrated with existing robot API on port 8000
- Windows scheduled task for boot persistence
