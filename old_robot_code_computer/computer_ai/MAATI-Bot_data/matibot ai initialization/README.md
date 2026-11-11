# MATI Bot System

Agricultural robotics system with 3-axis gantry, IP cameras, OAK depth camera, and SAM3 segmentation.

## Documentation Index

| Document | Purpose |
|----------|---------|
| **README.md** | This file - system overview and index |
| **mati bot api toolkit.md** | Complete API reference for all services (ports, endpoints, commands) |
| **ssh_toolkit.md** | SSH access to Windows host, gantry API commands |
| **arm calibration.md** | Servo arm calibration procedures |
| **ssh_windows_setup.txt** | Windows SSH configuration notes |

## Project Structure

```
MAATI-Bot_data/
├── matibot ai initialization/    # All setup/integration docs (this folder)
│   ├── README.md                  # This index
│   ├── mati bot api toolkit.md    # API reference
│   ├── ssh_toolkit.md            # SSH access guide
│   ├── arm calibration.md         # Arm calibration
│   └── ssh_windows_setup.txt     # Windows SSH setup
├── find_leaf_and_move.py          # Main leaf-finding navigation script
├── arduino_api_new.py             # Flask API for gantry control (Windows)
├── gantry_controller_mega.ino     # Arduino Mega gantry firmware
├── ip_calibration/                # Camera calibration data
├── raw_capture/                   # IP camera images
└── segments/                     # SAM3 segmentation results
```

## Quick Start

1. **SSH to Windows:** `ssh mahim@192.168.1.2`
2. **Check gantry API:** `curl http://192.168.1.2:8000/api/health`
3. **Run leaf finding:** `python3 find_leaf_and_move.py`

## System Components

- **Gantry API** (Windows:8000) - Motor control, positioning
- **IP Camera API** (Linux:8224) - RTSP capture, ArUco detection
- **OAK API** (Linux:8225) - RGB + Depth capture
- **SAM3 API** (Docker:8222) - Object segmentation

## Services

| Service | Port | Host |
|---------|------|------|
| Gantry/Hardware | 8000 | 192.168.1.2 |
| IP Camera | 8224 | localhost |
| OAK Depth | 8225 | localhost |
| SAM3 Segmentation | 8222 | localhost |

For detailed API endpoints and commands, see **mati bot api toolkit.md**.
For SSH access and network configuration, see **ssh_toolkit.md**.