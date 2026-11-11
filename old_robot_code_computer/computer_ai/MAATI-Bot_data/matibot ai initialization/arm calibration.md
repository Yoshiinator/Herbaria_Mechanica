# MATI Bot Arm Calibration

Documents arm home position and camera-to-robot calibration for the MAATI Bot system.

---

## Camera Calibration (Camera Index 1)

**Date:** 2026-05-12

**Calibration Images:** 52 chessboard captures
**Mean Reprojection Error:** 0.031

### Camera Matrix
```
[[412.16, 0.00, 329.02],
 [0.00, 409.66, 212.46],
 [0.00, 0.00, 1.00]]
```

### Distortion Coefficients
```
[-0.25, 0.09, 0.02, 0.00, -0.03]
```

### Image Size
- Width: 640
- Height: 480

**Saved to:** `/mnt/MAATI-Bot_data/calibration/camera_calibration.json`

**Undistortion:** Applied by default on /capture and /aruco_detect endpoints

---

## ArUco Marker Configuration

| Property | Value |
|----------|-------|
| Dictionary | DICT_4X4_50 |
| Marker ID | 0 |
| Marker Size | 100mm (10cm) |
| Grid | 4x4 |

---

## Gantry Calibration (2026-05-12)

**Home Position (ArUco at ZERO):** (406.75, 225.25) pixels

### Movement Ratios (Latest)
| Axis | Ratio |
|------|-------|
| X | 10.97 px/cm |
| Y | 10.65 px/cm |

### Direction Rules (CRITICAL)
- **Gantry +X** → marker moves LEFT in image (-X pixels)
- **Gantry +Y** → marker moves DOWN in image (+Y pixels)
- **Gantry -X** → marker moves RIGHT in image (+X pixels)
- **Gantry -Y** → marker moves UP in image (-Y pixels)

### Offset Adjustments (Verified)
| Offset | Value | Use |
|--------|-------|-----|
| X | +6 px | Gripper tip offset from ArUco center |
| Y | +4 px | Gripper tip offset from ArUco center |

### Move Calculation
To move from current ArUco position (cx, cy) to target:
- dx = target_x - cx + offset_x
- dy = target_y - cy + offset_y
- gantry_x = -dx / RATIO_X
- gantry_y = dy / RATIO_Y

---

## Pick and Place Workflow

1. **Capture image** → `/capture?camera_index=1`
2. **Segment** → SAM3 with text prompt
3. **Find object** → get center pixel (cx, cy)
4. **Detect ArUco** → get current marker position
5. **Calculate offset** → dx = object_x - aruco_x, dy = object_y - aruco_y
6. **Move to object** → gantry x+(-dx/10.97) y+(dy/10.65)
7. **Lower Z** → z+10
8. **Grip** → `/api/arm/grip`
9. **Raise Z** → z-10
10. **Home** → (follow home sequence rule below)
11. **Release** → `/api/arm/release`

---

## Home Sequence Rule (IMPORTANT)

**Always execute before homing:**
1. First: Move Z to 0 (zero)
2. Then: Move X and Y to 0 (zero)

**Why:** Z must be zero before X/Y homing to avoid collision and ensure accurate positioning.

**Correct homing sequence:**
```bash
# First reset Z
curl -X POST http://192.168.1.2:8000/api/gantry/move -d '{"cmd": "z-10"}'

# Then reset X and Y
curl -X POST http://192.168.1.2:8000/api/gantry/move -d '{"cmd": "x-N y-M"}'
```

**Never home X/Y while Z is raised - risk of hitting objects.**

---

## Reference Point (Marker Center at Zero Position)

The marker center (406.75, 225.25) represents the camera view of the arm at gantry position (0, 0, 0).

This is the calibration origin. All future ArUco detections use this as reference:
- Pixel offset from (452.0, 68.0) = arm movement direction

---

## Coordinate Systems

| System | Origin | Units |
|--------|--------|-------|
| Image | Top-left pixel (0,0) | pixels |
| Marker Center (zero) | (435.5, 69.5) at gantry (0,0,0) | pixels |
| Gantry | Machine origin (0,0,0) | cm |
| World | Arm home position | cm |

---

## Workflow: Find Arm Position from Image

```
1. Detect ArUco marker → get center (cx, cy)
2. Calculate pixel offset: dx = target_x - cx, dy = target_y - cy
3. Apply calibration: gantry_x = -dx/10.97, gantry_y = dy/10.65
4. Result: arm movement needed in cm
```

---

## Calibration History

**Updated:** 2026-05-12
- Camera calibration: 52 images, reprojection error 0.031
- Distortion coefficients: [-0.25, 0.09, 0.02, 0.00, -0.03] - relatively low distortion
- Gantry ratios: X=10.97 px/cm, Y=10.65 px/cm
- Home ArUco: (452.0, 68.0) - recalibrated 2026-05-12