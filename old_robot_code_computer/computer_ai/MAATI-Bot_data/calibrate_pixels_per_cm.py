#!/usr/bin/env python3
"""
ArUco Pixel/cm Calibration Script

Sequential calibration: move from current position, don't reset between moves.
Measures pixel travel for X and Y axes.

Sequence:
  home -> X+10 -> Y+10 -> X-10 -> Y-10 -> X+20 -> Y+20 -> Y-20 -> X-20 -> X+30 -> Y+30 -> Y-30 -> X-30
"""

import argparse
import json
import time
import requests
import os

# Configuration
CAMERA_HOST = "localhost"
CAMERA_PORT = 8224
GANTRY_HOST = "192.168.1.2"
GANTRY_PORT = 8000
MARKER_ID = 0
CALIB_OUTPUT = "/home/pairaiworkstation/MAATI-Bot_data/ip_calibration/pixels_per_cm.json"

def get_aruco(camera_index=0, undistort=False):
    """Detect ArUco marker and return center position."""
    url = f"http://{CAMERA_HOST}:{CAMERA_PORT}/aruco_detect?camera_index={camera_index}"

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("success") and data.get("markers_detected", 0) > 0:
                for marker in data.get("markers", []):
                    if marker.get("id") == MARKER_ID:
                        return (marker["center"]["x"], marker["center"]["y"])
            requests.get(f"http://{CAMERA_HOST}:{CAMERA_PORT}/capture?camera_index={camera_index}", timeout=5)
        except:
            pass
        time.sleep(0.5)
    return None

def capture_fresh(camera_index=0, count=5):
    """Capture frames to flush buffer."""
    for _ in range(count):
        try:
            requests.get(f"http://{CAMERA_HOST}:{CAMERA_PORT}/capture?camera_index={camera_index}", timeout=5)
        except:
            pass
        time.sleep(0.3)

def gantry_move(x=None, y=None, z=None):
    """Move gantry by x, y, z cm."""
    url = f"http://{GANTRY_HOST}:{GANTRY_PORT}/api/gantry/move"
    payload = {}
    if x is not None:
        payload["x"] = x
    if y is not None:
        payload["y"] = y
    if z is not None:
        payload["z"] = z
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as e:
        print(f"Gantry move error: {e}")
        return None

def gantry_pos():
    """Get current gantry position."""
    url = f"http://{GANTRY_HOST}:{GANTRY_PORT}/api/gantry/pos"
    try:
        resp = requests.get(url, timeout=10)
        return resp.json()
    except:
        return None

def wait_for_marker(camera_index=0, retries=10, delay=1):
    """Wait for marker detection with retries."""
    for i in range(retries):
        capture_fresh(camera_index, count=3)
        pos = get_aruco(camera_index)
        if pos:
            return pos
        time.sleep(delay)
    return None

def run_calibration(camera_index=0):
    """
    Run sequential calibration.

    1. Detect home marker
    2. Execute sequence: X+10, Y+10, X-10, Y-10, X+20, Y+20, Y-20, X-20, X+30, Y+30, Y-30, X-30
    3. Calculate pixels/cm from positive moves only
    """
    results = {
        "measurements": [],
        "timestamp": int(time.time()),
        "marker_id": MARKER_ID,
        "camera_index": camera_index
    }

    print("=== ArUco Calibration ===")

    # Step 1: Home position
    print("\nStep 1: Detecting home position...")
    capture_fresh(camera_index, count=8)
    home = get_aruco(camera_index)
    if not home:
        print("ERROR: Cannot detect home marker!")
        return None
    print(f"Home: ({home[0]}, {home[1]})")
    results["home"] = {"x": home[0], "y": home[1], "gantry": (0, 0, 0)}

    # Sequence: (axis, distance)
    sequence = [
        ("x", 10),
        ("y", 10),
        ("x", -10),
        ("y", -10),
        ("x", 20),
        ("y", 20),
        ("y", -20),
        ("x", -20),
        ("x", 30),
        ("y", 30),
        ("y", -30),
        ("x", -30),
    ]

    current_pos = home
    print("\nStep 2: Sequential moves...")

    for axis, dist in sequence:
        # Move
        if axis == "x":
            gantry_move(x=dist)
        else:
            gantry_move(y=dist)

        time.sleep(0.5)  # Brief pause after gantry response

        # Wait 40s for gantry to fully stop before capturing
        print(f"    Waiting 15s for gantry to settle...")
        time.sleep(15)

        # Detect
        pos = wait_for_marker(camera_index)
        if not pos:
            print(f"  {axis}{dist:+d}: FAILED - marker lost")
            results["measurements"].append({
                "move": f"{axis}{dist:+d}",
                "success": False
            })
        else:
            if axis == "x":
                delta = abs(pos[0] - current_pos[0])
            else:
                delta = abs(pos[1] - current_pos[1])

            px_per_cm = delta / abs(dist) if dist != 0 else 0

            print(f"  {axis}{dist:+d}: ({pos[0]}, {pos[1]}) delta={delta:.1f}px, {px_per_cm:.2f} px/cm")

            results["measurements"].append({
                "move": f"{axis}{dist:+d}",
                "axis": axis,
                "distance": dist,
                "marker_pos": {"x": pos[0], "y": pos[1]},
                "pixel_delta": delta,
                "pixels_per_cm": px_per_cm,
                "success": True
            })

            current_pos = pos

    # Calculate averages from positive moves
    x_positive = [m["pixels_per_cm"] for m in results["measurements"] if m.get("success") and m["axis"] == "x" and m["distance"] > 0]
    y_positive = [m["pixels_per_cm"] for m in results["measurements"] if m.get("success") and m["axis"] == "y" and m["distance"] > 0]

    results["x_pixels_per_cm_avg"] = sum(x_positive) / len(x_positive) if x_positive else 0
    results["y_pixels_per_cm_avg"] = sum(y_positive) / len(y_positive) if y_positive else 0
    results["x_measurements"] = len(x_positive)
    results["y_measurements"] = len(y_positive)

    print(f"\n=== Results ===")
    print(f"X-axis: {results['x_pixels_per_cm_avg']:.2f} px/cm (from {len(x_positive)} measurements)")
    print(f"Y-axis: {results['y_pixels_per_cm_avg']:.2f} px/cm (from {len(y_positive)} measurements)")

    return results

def save_calibration(results, output_path):
    """Save calibration results to JSON."""
    if results:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ArUco pixel/cm calibration")
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--save", action="store_true", default=True)
    parser.add_argument("--output", default=CALIB_OUTPUT)
    args = parser.parse_args()

    results = run_calibration(camera_index=args.camera_index)

    if results and args.save:
        save_calibration(results, args.output)