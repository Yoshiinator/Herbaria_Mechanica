# Script Toolkit

Automation scripts for MATI Bot operations.

---

## Leaf Finding & Navigation

### find_leaf_and_move.py
Find leaf using rectangular crop and move gantry to it.

```bash
cd /home/pairaiworkstation/MAATI-Bot_data
python3 find_leaf_and_move.py
```

**Flow:**
1. Get rectangular crop from `/crop_rectangle` (camera 0)
2. Send to SAM3 segmentation ("leaf" prompt)
3. Get leaf bounding box
4. Calculate gantry position from pixel coordinates
5. Move gantry to leaf position

**Key Config:**
- `PX_PER_CM = 14.6` (pixel to cm conversion, measured: 20cm = 292.7px)
- Home marker: X=1159, Y=242

---

## Calibration

### calibrate_pixels_per_cm.py
ArUco-based sequential calibration for pixel-to-cm conversion.

```bash
cd /home/pairaiworkstation/MAATI-Bot_data
python3 calibrate_pixels_per_cm.py
```

**Process:**
Sequential moves without reset:
`home → X+10 → Y+10 → X-10 → Y-10 → X+20 → Y+20 → Y-20 → X-20 → X+30 → Y+30 → Y-30 → X-30`

**Output:** `/home/pairaiworkstation/MAATI-Bot_data/ip_calibration/pixels_per_cm.json`

---

## Camera Services

### scripts/ip-capture-server.py
IP camera capture server (runs on Linux).

```bash
cd /home/pairaiworkstation/MAATI-Bot_data/scripts
python3 ip-capture-server.py
```

---

## Quick Commands

```bash
# Find and move to leaf
python3 find_leaf_and_move.py

# Calibrate pixels per cm
python3 calibrate_pixels_per_cm.py

# Check gantry position
curl http://192.168.1.2:8000/api/gantry/pos

# Move gantry
curl -X POST http://192.168.1.2:8000/api/gantry/move \
  -H 'Content-Type: application/json' \
  -d '{"cmd": "x+10 y-5"}'
```