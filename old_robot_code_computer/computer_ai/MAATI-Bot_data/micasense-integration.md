# MicaSense Altum Integration - Complete Scene

## Overview
Integrated MicaSense Altum multispectral camera into farm system. Captured images, converted, sent to users.

---

## Starting Point
- User connected camera to UniFi switch port 8
- Sent MicaSense support article: https://support.micasense.com/hc/en-us/articles/360044191493-How-to-connect-to-the-MicaSense-Altum-via-Ethernet
- This was a NEW device I hadn't used before

---

## Step 1: Documentation

### Manual Read
Located and read: `/home/pairaiworkstation/MAATI-Bot_data/micasense-altum-manual.pdf

Manual contents:
- Default IP: 192.168.1.101
- 6 spectral bands with wavelengths:
  - Blue: 475nm
  - Green: 560nm
  - Red: 668nm
  - NIR: 842nm
  - Red Edge: 717nm
  - Thermal: 11μm (LWIR)
- SD card storage required
- HTTP REST API
- External 12V power supply

---

## Step 2: Finding Camera

Expected IP 192.168.1.101 - NO RESPONSE

Ran ping sweep:
```
for ip in 192.168.1.{1..254}; do ping -c 1 $ip; done
```

**FOUND: 192.168.1.83** (different from manual spec!)

---

## Step 3: API Testing

Testing endpoints with curl:

```
curl http://192.168.1.83/config
```
Response:
```json
{
  "agc_minimum_mean": 0.17,
  "audio_enable": true,
  "auto_cap_mode": "disabled",
  "ip_address": "192.168.1.83",
  "network_mode": "main",
  "operating_alt": 107,
  ...
}
```

```
curl http://192.168.1.83/status
```
Response:
```json
{
  "serial_number": "023-05106-138",
  "wifi_type": "disabled",
  "sd_card": "NotPresent",  ← PROBLEM!
  "capture_status": "ready"
}
```

```
curl http://192.168.1.83/files/
```
Response:
```json
{
  "directories": ["System Volume Information", "0000SET"],
  "files": []
}
```

---

## Step 4: SD Card Issue

Problem: Camera not detecting SD card

User said: "its in. its not detecting"

Solution: User reseated SD card firmly in slot

Rechecked status:
```json
{
  "sd_card": "Available",
  "sd_free": 966810880,
  "sd_size": 1038098432
}
```
≈ 0.93GB free ✅

---

## Step 5: First Capture

Trigger capture:
```
curl -X POST http://192.168.1.83/capture
```
Response:
```json
{"id": "Y219hdQ0ZMKOvfonCLAH", "status": "pending"}
```

Wait 2 seconds, check files:
```
curl http://192.168.1.83/files/0000SET/000/
```
Response:
```json
{
  "files": [
    {"name": "IMG_0000_1.tif", "size": 6380340},
    {"name": "IMG_0000_2.tif", "size": 6380420},
    {"name": "IMG_0000_3.tif", "size": 6380410},
    {"name": "IMG_0000_4.tif", "size": 6380408},
    {"name": "IMG_0000_5.tif", "size": 6380414},
    {"name": "IMG_0000_6.tif", "size": 44452}
  ]
}
```

6 bands captured:
| Index | Band | Wavelength | Size |
|-------|------|-----------|------|
| 1 | Blue | 475nm | 6.1MB |
| 2 | Green | 560nm | 6.1MB |
| 3 | Red | 668nm | 6.1MB |
| 4 | NIR | 842nm | 6.1MB |
| 5 | Red Edge | 717nm | 6.1MB |
| 6 | Thermal | 11μm | 44KB |

---

## Step 6: Download

Download command:
```
curl -o blue.tif http://192.168.1.83/files/0000SET/000/IMG_0000_1.tif
curl -o green.tif http://192.168.1.83/files/0000SET/000/IMG_0000_2.tif
curl -o red.tif http://192.168.1.83/files/0000SET/000/IMG_0000_3.tif
curl -o nir.tif http://192.168.1.83/files/0000SET/000/IMG_0000_4.tif
curl -o rededge.tif http://192.168.1.83/files/0000SET/000/IMG_0000_5.tif
curl -o thermal.tif http://192.168.1.83/files/0000SET/000/IMG_0000_6.tif
```

Saved to: `/home/pairaiworkstation/MAATI-Bot_data/altum_captures/`

---

## Step 7: Convert to Telegram Format

Problem: TIFF files too big (~6MB each)
Telegram limit: ~20MB but large files take long to upload

Python conversion:
```python
from PIL import Image
import numpy as np

# Open 16-bit TIFF
img = Image.open('red.tif')
img = img.convert('I')
arr = np.array(img)

# Stretch to 0-255
arr = ((arr - arr.min()) / (arr.max() - arr.min()) * 255).astype(np.uint8)
img8 = Image.fromarray(arr)

# Resize for Telegram
img8.thumbnail((480, 360), Image.Resampling.LANCZOS)

# Save as JPEG
img8.save('red.jpg', quality=85)
```

Result: ~3-400KB per image

---

## Step 8: Send to Users

Sent 5 bands (no thermal) to both Telegram users:

**Chat 1 (7674508568):**
- Blue ✅
- Green ✅
- Red ✅
- NIR ✅
- Red Edge ✅

**Chat 2 (6365998279):**
- Blue ✅
- Green ✅
- Red ✅
- NIR ✅
- Red Edge ✅

---

## Step 9: Additional Captures

**Set 2:**
- Captured IMG_0001_*.tif
- Downloaded to altum_set2/
- Converted and sent

**Set 3:**
- User requested "RGB" image
- Captured, downloaded
- Converted Red band (Band 3) to viewable JPEG
- Sent to both users

---

## Step 10: Calibration Question

User asked: "is there an calib?"

Checked:
- No separate calibration file on SD card
- Manual indicates calibration coefficients embedded in TIFF EXIF metadata
- Software (Pix4D, QGIS, etc.) reads automatically
- This is standard for radiometric calibration

---

## User Corrections

### Correction 1: Power Supply
I assumed: PoE powered (like other devices)

User corrected: External 12V power supply, NOT PoE

### Correction 2: Network Access
I kept trying to SSH to NUC (192.168.1.2)

User corrected: ALL devices accessible directly from this Linux machine
- Only use NUC for robot/gantry motor control

Updated memory:
> "All network devices accessible DIRECTLY from this Linux machine - no SSH to NUC needed for camera stuff. MicaSense Altum at 192.168.1.83, IP cams at .51/.52/.57, UniFi at .1/.53/.58. Only SSH to NUC (192.168.1.2) for robot motor control."

---

## Final Integration

### Equipment
- **Camera:** MicaSense Altum multispectral
- **IP:** 192.168.1.83
- **Switch Port:** 8
- **Power:** External 12V supply (not PoE)
- **Storage:** SD card (SanDisk, ~0.93GB free)

### API Endpoints
```
http://192.168.1.83/capture     POST   Trigger capture
http://192.168.1.83/status    GET    Camera status
http://192.168.1.83/files/    GET    List directories
http://192.168.1.83/files/0000SET/000/  GET  List images
http://192.168.1.83/config   GET    Camera config
```

### Capture Workflow
```bash
# 1. Trigger capture
curl -X POST http://192.168.1.83/capture

# 2. Wait 2-3 seconds

# 3. List captured files
curl http://192.168.1.83/files/0000SET/000/

# 4. Download band
curl -o band.tif http://192.168.1.83/files/0000SET/000/IMG_XXXX_Y.tif

# 5. Downloaded files location:
# /home/pairaiworkstation/MAATI-Bot_data/altum_captures/
# /home/pairaiworkstation/MAATI-Bot_data/altum_set2/
# /home/pairaiworkstation/MAATI-Bot_data/altum_set3/
```

---

## Files Created
- `/home/pairaiworkstation/MAATI-Bot_data/altum_captures/` - Set 1 TIFFs + JPGs
- `/home/pairaiworkstation/MAATI-Bot_data/altum_set2/` - Set 2 TIFFs + JPGs
- `/home/pairaiworkstation/MAATI-Bot_data/altum_set3/` - Set 3 TIFFs + JPGs

Camera IP saved in memory ✅