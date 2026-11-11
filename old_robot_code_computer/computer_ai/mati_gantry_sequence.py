#!/usr/bin/env python3
"""MAATI Gantry Sequence - relative moves, capture after each position"""
import requests
import time

GANTRY_URL = "http://192.168.1.2:8000"
CAPTURE_URL = "http://localhost:8225/usb_capture?cam=1"

# Track position locally (relative moves)
current_x = 0.0
current_y = 0.0

def move_gantry(x=None, y=None, z=None):
    """Move gantry RELATIVE to current position"""
    global current_x, current_y
    payload = {}
    if x is not None and x != 0:
        payload["x"] = x
        current_x += x
    if y is not None and y != 0:
        payload["y"] = y
        current_y += y
    if z is not None:
        payload["z"] = z
    if not payload:
        return {"ok": True, "data": "no move needed"}
    resp = requests.post(f"{GANTRY_URL}/api/gantry/move", json=payload, timeout=10)
    return resp.json()

def wait_for_idle(timeout=60, api_timeout=10):
    """Wait until gantry stops moving by checking pos stability.
    Uses longer timeouts for long moves where API may be unresponsive."""
    start = time.time()
    last_pos = None
    stable_count = 0
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{GANTRY_URL}/api/gantry/pos", timeout=api_timeout)
            data = resp.json()
            if data.get("ok"):
                pos_str = data.get("data", "")
                paren_pos = pos_str.find("(")
                if paren_pos != -1:
                    coords = pos_str[paren_pos+1:].split(")")[0]
                    parts = coords.split(",")
                    cx = float(parts[0])
                    cy = float(parts[1])
                    # Wait for 3 consecutive stable readings
                    if last_pos is None or abs(cx - last_pos[0]) < 0.1 and abs(cy - last_pos[1]) < 0.1:
                        stable_count += 1
                    else:
                        stable_count = 0
                    last_pos = (cx, cy)
                    if stable_count >= 3:
                        return True
        except requests.exceptions.RequestException:
            # API busy/unresponsive during long move — keep waiting
            pass
        time.sleep(1)
    return False

def capture():
    """Capture image with USB cam 1, return file path"""
    resp = requests.get(CAPTURE_URL, timeout=10)
    result = resp.json()
    return result["file_path"]

def send_image(img_path):
    """Send image to telegram"""
    from hermes_tools import send_message
    send_message(action="send", target="telegram:7674508568", message=f"MEDIA:{img_path}")

def run_sequence():
    # Relative moves from current position
    # Start: (0,0) → x+19 → x+11 → y+20 → x-11 → x-19,y-20
    moves = [
        (22, 0),    # step 1: x to 22
        (12, 0),    # step 2: x to 34
        (0, 20),    # step 3: y to 20
        (-12, 0),   # step 4: x back to 22
        (-22, -20), # step 5: back to 0,0
    ]

    for i, (dx, dy) in enumerate(moves):
        print(f"\nStep {i+1}: Move RELATIVE dx={dx}, dy={dy}")
        print(f"  Expected pos after move: ({current_x + dx:.2f}, {current_y + dy:.2f})")
        move_gantry(x=dx, y=dy)
        reached = wait_for_idle()
        if reached:
            print(f"  Arrived at ~({current_x:.2f}, {current_y:.2f})")
        else:
            print(f"  WARNING: Timeout at ~({current_x:.2f}, {current_y:.2f})")
        time.sleep(0.3)
        print("  Capturing...")
        img = capture()
        print(f"  Captured: {img}")
        try:
            send_image(img)
            print(f"  Sent to telegram!")
        except Exception as e:
            print(f"  Send failed: {e}")
        time.sleep(0.3)

    print("\nSequence complete!")

if __name__ == "__main__":
    run_sequence()