# SSH Toolkit for MATI Bot System

SSH access configuration and commands for AGROBOT (Windows) and Linux services.

---

## Windows Host (AGROBOT)

**IP:** `192.168.1.2`
**User:** `mahim`
**Password:** `1234`
**Hostname:** AGROBOT

### SSH Key Setup (completed)
Public key added to `C:\ProgramData\ssh\administrators_authorized_keys` on AGROBOT.

### Connect without password
```bash
ssh mahim@192.168.1.2
```

### Connect with password (fallback)
```bash
sshpass -p "1234" ssh mahim@192.168.1.2
```

---

## Useful Commands on AGROBOT

```bash
# Check if API server is running
netstat -ano | findstr 8000

# Check API health
curl http://localhost:8000/api/health

# Check gantry position
curl http://localhost:8000/api/gantry/pos

# Check all pump statuses
curl http://localhost:8000/api/pump/all/status

# Restart SSH service
powershell -Command "Restart-Service sshd"

# Check SSH config
type C:\ProgramData\ssh\sshd_config

# List Arduino boards
C:\arduino-cli\arduino-cli.exe board list
```

---

## Arduino CLI (on AGROBOT)

**Location:** `C:\arduino-cli\arduino-cli.exe`
**Version:** 1.5.0

### Installed Cores
| Core | Version |
|------|---------|
| arduino:avr | 1.8.7 |
| esp32 | 3.3.7 |

### Connected Boards
```
Port    Protocol  Type                    Board Name               FQBN             Core
COM3    serial    Serial Port (USB)       Arduino Mega or Mega 2560 arduino:avr:mega arduino:avr
COM4    serial    Serial Port (USB)       Arduino Mega or Mega 2560 arduino:avr:mega arduino:avr
```

### Compile and Upload

```bash
# Compile gantry controller
ssh mahim@192.168.1.2 "arduino-cli compile --fqbn arduino:avr:mega C:\sharedfiles\gantry_controller"

# Upload to COM4 (gantry)
ssh mahim@192.168.1.2 "arduino-cli upload -p COM4 --fqbn arduino:avr:mega C:\sharedfiles\gantry_controller"

# Upload to COM3 (servo)
ssh mahim@192.168.1.2 "arduino-cli upload -p COM3 --fqbn arduino:avr:mega C:\sharedfiles\servo_control"

# Monitor serial
ssh mahim@192.168.1.2 "arduino-cli monitor -p COM4"
```

---

## Gantry/Hardware API

**Endpoint:** `http://192.168.1.2:8000`

### Gantry API Commands

```bash
# Move gantry (relative)
curl -X POST "http://192.168.1.2:8000/api/gantry/move" \
  -H 'Content-Type: application/json' \
  -d '{"cmd": "x+10 y-5"}'

# Or use individual axes
curl -X POST "http://192.168.1.2:8000/api/gantry/move" \
  -H 'Content-Type: application/json' \
  -d '{"x": 10, "y": -5, "z": 0}'

# Get current position
curl "http://192.168.1.2:8000/api/gantry/pos"

# Reset position to (0,0,0)
curl -X POST "http://192.168.1.2:8000/api/gantry/reset"

# Move to home position
curl -X POST "http://192.168.1.2:8000/api/gantry/home"

# Health check
curl "http://192.168.1.2:8000/api/health"
```

### Servo/Arm Commands

```bash
# Set servo angle
curl -X POST http://192.168.1.2:8000/api/servo/set \
  -H 'Content-Type: application/json' \
  -d '{"servo": 1, "angle": 90}'

# Get all servo angles
curl "http://192.168.1.2:8000/api/servo/all"

# Reset all servos
curl -X POST http://192.168.1.2:8000/api/servo/reset

# Close gripper (servo 1 to 100°)
curl -X POST http://192.168.1.2:8000/api/arm/grip

# Open gripper (servo 1 to 0°)
curl -X POST http://192.168.1.2:8000/api/arm/release

# Full API documentation
curl "http://192.168.1.2:8000/api/howto"
```

---

## Source Code Locations (on AGROBOT)

**Path:** `C:\sharedfiles\`

Contents:
- `pump_api_update.py` - Arduino API service (FastAPI) with pump support
- `gantry_controller/` - Gantry Arduino source (.ino)
- `servo_control/` - Servo Arduino source (.ino)
- `start_api.ps1` - API startup script
- `setup_auto_start.ps1` - Auto-start configuration

### Access via SSH
```bash
ssh mahim@192.168.1.2 "dir C:\sharedfiles"
```

### Copy from Windows to Linux
```bash
sshpass -p "1234" scp -r "mahim@192.168.1.2:C:/sharedfiles/." /local/path/
```

---

## Troubleshooting

### "Permission denied" on SSH key
- Check key is in `C:\ProgramData\ssh\administrators_authorized_keys`
- Verify `sshd_config` doesn't have `Match Group administrators` blocking it
- Fix: `(Get-Content C:\ProgramData\ssh\sshd_config) -replace 'Match Group administrators', '#Match Group administrators' | Set-Content C:\ProgramData\ssh\sshd_config; Restart-Service sshd`

### Can't connect at all
- Ping test: `ping 192.168.1.2`
- Check SSH service: `sshd` should be running on Windows
- Firewall may be blocking port 22

### Gantry shows `false` (COM4 busy)
- Close other programs using COM4
- API will auto-reconnect when port is free

---

## SSH Key Generation (if needed again)

```bash
# Generate SSH key
ssh-keygen -t rsa -f ~/.ssh/id_rsa -N ""

# Copy key to Windows
sshpass -p "1234" ssh-copy-id -i ~/.ssh/id_rsa.pub mahim@192.168.1.2

# Or manually add to Windows
# Copy ~/.ssh/id_rsa.pub content and run on Windows:
powershell -Command "Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value 'YOUR_PUBLIC_KEY'"
```

---

## File Locations

| File | Linux Path |
|------|------------|
| This toolkit | /home/pairaiworkstation/MAATI-Bot_data/matibot ai initialization/ssh_toolkit.md |
| Project data | /home/pairaiworkstation/MAATI-Bot_data |
| Windows host data | \\192.168.1.50\MAATI-Bot_data |