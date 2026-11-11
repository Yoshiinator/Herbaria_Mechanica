#!/usr/bin/env python3
"""
Find and Capture at 4 fixed positions.
At each position: capture raw image → SAM3 segment → crop → save.
Replaces detection-based 3-position move with fixed 4-position sequence.
Positions: (22,0) → (34,0) → (34,20) → (22,20) → home (0,0)
"""

import requests
import time
import os
import json
from datetime import datetime

# Configuration
CAMERA_HOST = "localhost"
CAMERA_PORT = 8225
SAM3_HOST = "localhost"
SAM3_PORT = 8222
GANTRY_HOST = "192.168.1.2"
GANTRY_PORT = 8000

# Output directory
OUTPUT_DIR = "/home/pairaiworkstation/MAATI-Bot_data/scanned_crops"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Home marker position (for coordinate reference)
HOME_MARKER_X = 1159
HOME_MARKER_Y = 242
PX_PER_CM = 14.6

# Fixed positions to scan (relative moves from current pos)
POSITIONS = [
    (22, 0),    # pos 1
    (12, 0),    # pos 2: x to 34
    (0, 20),    # pos 3: y to 20
    (-12, 0),   # pos 4: x back to 22
    (-22, -20), # pos 5: home
]

# Track position locally
current_x = 0.0
current_y = 0.0


def move_gantry(dx, dy):
    """Move gantry RELATIVE to current position."""
    global current_x, current_y
    payload = {}
    if dx != 0:
        payload["x"] = dx
        current_x += dx
    if dy != 0:
        payload["y"] = dy
        current_y += dy
    if not payload:
        return {"ok": True, "data": "no move needed"}
    url = f"http://{GANTRY_HOST}:{GANTRY_PORT}/api/gantry/move"
    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def wait_for_idle(timeout=60, api_timeout=10):
    """Wait until gantry stops moving by checking pos stability."""
    start = time.time()
    last_pos = None
    stable_count = 0
    while time.time() - start < timeout:
        try:
            url = f"http://{GANTRY_HOST}:{GANTRY_PORT}/api/gantry/pos"
            resp = requests.get(url, timeout=api_timeout)
            data = resp.json()
            if data.get("ok"):
                pos_str = data.get("data", "")
                paren_pos = pos_str.find("(")
                if paren_pos != -1:
                    coords = pos_str[paren_pos+1:].split(")")[0]
                    parts = coords.split(",")
                    cx = float(parts[0])
                    cy = float(parts[1])
                    if last_pos is None or (abs(cx - last_pos[0]) < 0.1 and abs(cy - last_pos[1]) < 0.1):
                        stable_count += 1
                    else:
                        stable_count = 0
                    last_pos = (cx, cy)
                    if stable_count >= 3:
                        return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


def capture_raw(camera_index=0):
    """Get fresh raw image from USB camera API."""
    url = f"http://{CAMERA_HOST}:{CAMERA_PORT}/usb_capture?usb_index={camera_index}"
    resp = requests.get(url, timeout=30)
    data = resp.json()
    if data.get("success"):
        local_path = data.get("file_path")
        sam_path = local_path.replace("/home/pairaiworkstation/MAATI-Bot_data", "/mnt/MAATI-Bot_data")
        print(f"  Captured: {local_path}")
        return (local_path, sam_path)
    print(f"  Capture failed: {data}")
    return (None, None)


def segment_sam3(sam_path, confidence=0.3, retries=3):
    """Send image to SAM3 and get all detections."""
    url = f"http://{SAM3_HOST}:{SAM3_PORT}/api/segment"

    for attempt in range(retries):
        files = {"file_path": (None, sam_path)}
        data = {"text_prompt": "leaf", "confidence_threshold": str(confidence)}

        resp = requests.post(url, files=files, data=data, timeout=60)
        resp.close()
        result = resp.json()

        if not result.get("success"):
            print(f"  SAM3 error: {result}")
            return None

        dets = result.get("metadata", {}).get("detections", [])
        if dets:
            print(f"  SAM3: {len(dets)} detection(s) at conf {confidence}")
            return dets

        print(f"  Attempt {attempt+1}: No detections at conf {confidence}")
        confidence = confidence / 2

    return []


def crop_and_save(local_path, dets, pos_label):
    """Crop around each detection and save."""
    import cv2
    img = cv2.imread(local_path)
    if img is None:
        print(f"  WARNING: Could not read {local_path}")
        return []

    saved = []
    for i, det in enumerate(dets):
        bb = det["bounding_box"]
        x_min = max(0, int(bb["x_min"]))
        y_min = max(0, int(bb["y_min"]))
        x_max = min(img.shape[1], int(bb["x_max"]))
        y_max = min(img.shape[0], int(bb["y_max"]))

        crop = img[y_min:y_max, x_min:x_max]
        if crop.size == 0:
            continue

        # Save crop
        fname = f"crop_{pos_label}_det{i+1}_conf{det.get('confidence',0):.2f}_{int(time.time())}.jpg"
        fpath = os.path.join(OUTPUT_DIR, fname)
        cv2.imwrite(fpath, crop)
        saved.append(fpath)
        print(f"  Saved crop: {fname}")

    return saved


def run():
    global current_x, current_y
    print("=== Find and Capture at 4 Fixed Positions ===")
    print(f"Positions: (22,0) → (34,0) → (34,20) → (22,20) → home")
    print()

    all_results = []

    for step, (dx, dy) in enumerate(POSITIONS):
        pos_label = f"pos{step+1}"

        # Move
        print(f"\n[{step+1}/5] Moving dx={dx}, dy={dy} → expected (~{current_x+dx:.0f}, {current_y+dy:.0f})")
        move_gantry(dx, dy)
        reached = wait_for_idle()
        if reached:
            print(f"  Arrived at ~(~{current_x:.1f}, {current_y:.1f})")
        else:
            print(f"  WARNING: Timeout at ~(~{current_x:.1f}, {current_y:.1f})")

        time.sleep(0.3)

        # Capture
        print(f"  Capturing...")
        local_path, sam_path = capture_raw(0)
        if not local_path:
            continue

        # Segment
        print(f"  Segmenting with SAM3...")
        dets = segment_sam3(sam_path)
        print(f"  Detections: {len(dets) if dets is not None else 0}")

        # Crop and save
        if dets:
            saved = crop_and_save(local_path, dets, pos_label)
        else:
            saved = []
            # Save full frame anyway
            fname = f"full_{pos_label}_nodetect_{int(time.time())}.jpg"
            fpath = os.path.join(OUTPUT_DIR, fname)
            import cv2
            cv2.imwrite(fpath, cv2.imread(local_path))
            saved.append(fpath)
            print(f"  No detections — saved full frame: {fname}")

        all_results.append({
            "step": step + 1,
            "position": (current_x, current_y),
            "detections": len(dets) if dets is not None else 0,
            "crops": saved,
        })

        time.sleep(0.3)

    # Summary
    print("\n=== Summary ===")
    total_dets = sum(r["detections"] for r in all_results)
    print(f"Total detections across all positions: {total_dets}")
    for r in all_results:
        print(f"  Step {r['step']} at ({r['position'][0]:.0f},{r['position'][1]:.0f}): {r['detections']} detections, {len(r['crops'])} crops saved")
    print(f"\nOutput dir: {OUTPUT_DIR}")
    print("Done!")


if __name__ == "__main__":
    run()