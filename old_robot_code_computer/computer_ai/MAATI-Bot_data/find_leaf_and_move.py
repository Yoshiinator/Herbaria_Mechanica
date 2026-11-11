#!/usr/bin/env python3
"""
Find leaf using fresh raw image from USB camera API.
1. Get raw image with /usb_capture API (camera 0)
2. Send to SAM3 for segmentation
3. Get leaf bounding box
4. Calculate gantry position from pixel coordinates
5. Move gantry to leaf position
"""

import requests
import time

# Configuration
CAMERA_HOST = "localhost"
CAMERA_PORT = 8225
SAM3_HOST = "localhost"
SAM3_PORT = 8222
GANTRY_HOST = "192.168.1.2"
GANTRY_PORT = 8000

# Home marker position
HOME_MARKER_X = 1159
HOME_MARKER_Y = 242

# Pixel to cm conversion (measured: 20cm = 292.7px -> 14.6 px/cm)
PX_PER_CM = 14.6

# Fixed marker positions for crop-to-camera mapping
MARKER7_X, MARKER7_Y = 1014.5, 521.0
MARKER9_X, MARKER9_Y = 3196.5, 1968.5

# Crop output size
CROP_W, CROP_H = 4000, 2000

def get_raw_image(camera_index=0):
    """Get fresh raw image from USB camera API."""
    url = f"http://{CAMERA_HOST}:{CAMERA_PORT}/usb_capture?usb_index={camera_index}"
    resp = requests.get(url, timeout=30)
    data = resp.json()
    if data.get("success"):
        local_path = data.get("file_path")
        sam_path = local_path.replace("/home/pairaiworkstation/MAATI-Bot_data", "/mnt/MAATI-Bot_data")
        print(f"Image saved: {local_path}")
        return (local_path, sam_path)
    print(f"Capture failed: {data}")
    return (None, None)

def segment_leaf(sam_path, confidence=0.3, retries=3):
    """Send image to SAM3 and get leaf bounding box. Retry with lower confidence if needed."""
    url = f"http://{SAM3_HOST}:{SAM3_PORT}/api/segment"

    for attempt in range(retries):
        files = {"file_path": (None, sam_path)}
        data = {"text_prompt": "leaf", "confidence_threshold": str(confidence)}

        resp = requests.post(url, files=files, data=data, timeout=60)
        resp.close()
        result = resp.json()

        if not result.get("success"):
            print(f"SAM3 error: {result}")
            return None

        dets = result.get("metadata", {}).get("detections", [])
        if dets:
            # Get largest detection by bounding box area
            largest = max(dets, key=lambda d:
                (d["bounding_box"]["x_max"] - d["bounding_box"]["x_min"]) *
                (d["bounding_box"]["y_max"] - d["bounding_box"]["y_min"])
            )
            bb = largest["bounding_box"]

            cx = (bb["x_min"] + bb["x_max"]) / 2
            cy = (bb["y_min"] + bb["y_max"]) / 2
            conf = largest.get("confidence", 0)

            print(f"Leaf at crop pixel: ({cx:.0f}, {cy:.0f}), conf={conf:.2f}")
            return (cx, cy)

        print(f"Attempt {attempt+1}: No detections at confidence {confidence}")
        confidence = confidence / 2  # Lower threshold for retry

    print("No detections found after retries")
    return None

def calculate_gantry(leaf_x, leaf_y):
    """Convert raw image pixel position to gantry cm position."""
    # Delta from home marker (marker 0 position in raw image)
    dx_px = leaf_x - HOME_MARKER_X
    dy_px = HOME_MARKER_Y - leaf_y  # Y inverted

    # Convert to cm using px/cm ratio
    dx_cm = (HOME_MARKER_X - leaf_x) / PX_PER_CM
    dy_cm = (leaf_y - HOME_MARKER_Y) / PX_PER_CM

    print(f"Leaf in raw image: ({leaf_x:.1f}, {leaf_y:.1f})")
    print(f"Gantry target: x={dx_cm:.1f}cm, y={dy_cm:.1f}cm")
    return (dx_cm, dy_cm)

def move_gantry(x, y):
    """Move gantry to position."""
    # Round to integers for API
    x = int(round(x))
    y = int(round(y))
    url = f"http://{GANTRY_HOST}:{GANTRY_PORT}/api/gantry/move"
    resp = requests.post(url, json={"x": x, "y": y}, timeout=30)
    result = resp.json()
    print(f"Gantry response: {result}")
    return result

def main():
    print("=== Find Leaf (Raw Image) and Move ===")
    print(f"PX_PER_CM = {PX_PER_CM}")

    # Step 1: Get raw image (camera 0)
    print("\n[1/4] Getting raw image (camera 0)...")
    local_path, sam_path = get_raw_image(0)
    if not local_path:
        print("ERROR: Failed to get image")
        return

    # Step 2: Segment with SAM3
    print("\n[2/4] Segmenting with SAM3...")
    result = segment_leaf(sam_path, confidence=0.3, retries=3)
    if not result:
        print("ERROR: No leaf found")
        return

    leaf_x, leaf_y = result

    # Step 3: Calculate gantry position
    print("\n[3/4] Calculating gantry position...")
    gantry_x, gantry_y = calculate_gantry(leaf_x, leaf_y)

    # Step 4: Move gantry
    print("\n[4/4] Moving gantry...")
    move_gantry(gantry_x, gantry_y)

    print("\n=== Done ===")

if __name__ == "__main__":
    main()