# MATI Bot API Toolkit

Quick reference for all service endpoints.

---

## Services

| Service | Port | URL | Status |
|---------|------|-----|--------|
| IP Camera | 8224 | http://localhost:8224 | Running |
| SAM3 Segmentation | 8222 | http://localhost:8222 | Running |
| USB Capture | 8223 | http://localhost:8223 | Running |
| Gantry/Hardware/Pump | 8000 | http://192.168.1.2:8000 | Running |
| OAK Depth | 8225 | http://localhost:8225 | Not running |

---

## IP Camera API (8224)

### Health Check
```bash
curl http://localhost:8224/health
```

### List Cameras
```bash
curl http://localhost:8224/cameras
```

### Capture Image
```bash
curl "http://localhost:8224/capture?camera_index=0"
```
Saves to: `/home/pairaiworkstation/MAATI-Bot_data/raw_capture/ip_capture_TIMESTAMP.jpg`

### ArUco Detection
```bash
curl "http://localhost:8224/aruco_detect?camera_index=0"
```
Detects markers 7, 8, 9, 10 (4x4 grid, 100mm size)

### Crop Rectangle
```bash
curl "http://localhost:8224/crop_rectangle?camera_index=0"
```
Uses markers 7,8,9,10 to crop 4ft x 2ft → 2000x1000px output.

### Calibration
```bash
# Capture chessboard images
curl "http://localhost:8224/calibration_capture?camera_index=0"

# Compute calibration
curl -X POST "http://localhost:8224/calibration_compute?camera_index=0"

# Get calibration data
curl "http://localhost:8224/calibration_info?camera_index=0"
```

---

## SAM3 Segmentation (8222)

### Segment Image
```bash
curl -X POST http://localhost:8222/api/segment \
  -F "file_path=/mnt/MAATI-Bot_data/raw_capture/image.jpg" \
  -F "text_prompt=leaf"
```

### Health Check
```bash
curl http://localhost:8222/health
```

---

## Gantry/Pump API (8000 on Windows)

**Base:** `http://192.168.1.2:8000`

**Devices:** Gantry (COM4), Servo (COM3), Pump (COM5)

### Health
```bash
curl http://192.168.1.2:8000/api/health
```
Returns: `{"ok":true,"gantry":true,"servo":true,"pump":true}`

### Status
```bash
curl http://192.168.1.2:8000/api/status
```

---

### Gantry Control

```bash
# Move gantry (relative, cm)
curl -X POST "http://192.168.1.2:8000/api/gantry/move" \
  -H 'Content-Type: application/json' \
  -d '{"cmd": "x+10 y-5"}'

# Or individual axes
curl -X POST "http://192.168.1.2:8000/api/gantry/move" \
  -H 'Content-Type: application/json' \
  -d '{"x": 10, "y": -5, "z": 0}'

# Get current position
curl "http://192.168.1.2:8000/api/gantry/pos"

# Reset position tracking to (0,0,0)
curl -X POST "http://192.168.1.2:8000/api/gantry/reset"

# Send to home position
curl -X POST "http://192.168.1.2:8000/api/gantry/home"
```

---

### Servo / Arm Control

```bash
# Set servo angle (1-4, 0-180 degrees)
curl -X POST "http://192.168.1.2:8000/api/servo/set" \
  -H 'Content-Type: application/json' \
  -d '{"servo": 1, "angle": 90}'

# Get all servo angles
curl "http://192.168.1.2:8000/api/servo/all"

# Reset all servos to 0
curl -X POST "http://192.168.1.2:8000/api/servo/reset"

# Gripper close (servo 1 to 100°)
curl -X POST "http://192.168.1.2:8000/api/arm/grip"

# Gripper open (servo 1 to 0°)
curl -X POST "http://192.168.1.2:8000/api/arm/release"
```

---

### Pump Control (COM5)

```bash
# Set pump speed (1-4, speed 0-255)
curl -X POST "http://192.168.1.2:8000/api/pump/1/set" \
  -H 'Content-Type: application/json' \
  -d '{"speed": 255}'

# Set pump with auto-off timer (seconds, max 3600)
curl -X POST "http://192.168.1.2:8000/api/pump/1/set_time" \
  -H 'Content-Type: application/json' \
  -d '{"speed": 255, "time": 10}'

# Stop pump
curl -X POST "http://192.168.1.2:8000/api/pump/1/stop"

# Get pump status
curl "http://192.168.1.2:8000/api/pump/1/status"

# Get all pump statuses
curl "http://192.168.1.2:8000/api/pump/all/status"

# Stop all pumps
curl -X POST "http://192.168.1.2:8000/api/pump/all/off"
```

---

## USB Camera (8223)

```bash
curl "http://localhost:8223/capture?camera_index=0"
curl "http://localhost:8223/aruco_detect?camera_index=0"
curl "http://localhost:8223/cameras"
```

---

## OAK Depth Camera (8225)

**Not running.** Start with:
```bash
/home/pairaiworkstation/oak-env/bin/python3 /home/pairaiworkstation/oak_api.py
```

Endpoints: `/capture`, `/depth`, `/depth_colormap`, `/health`

---

## Data Paths

| Type | Linux | Windows |
|------|-------|---------|
| Project | /home/pairaiworkstation/MAATI-Bot_data | \\192.168.1.50\MAATI-Bot_data |
| SAM3 Mount | /mnt/MAATI-Bot_data | \\mnt\MAATI-Bot_data |
| Raw Images | raw_capture/ | raw_capture/ |
| Calibration | ip_calibration/ | ip_calibration/ |

---

## Camera IPs

- **Camera 0:** rtsp://admin:Agribot%401234@192.168.1.52:554/
- **Camera 1:** rtsp://admin:Agribot%401234@192.168.1.57:554/