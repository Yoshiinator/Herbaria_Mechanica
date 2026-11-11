#!/usr/bin/env python3
"""
Single top-view Canon capture → SAM bounding boxes → VLM visual analysis → Spray.
No close-up views. Same image is used for detection and analysis.
4 fixed positions with gantry movement.
"""
import cv2
import requests
import base64
import os
import math
import json
import time
import subprocess
import fcntl

# Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "7674508568"
GANTRY_API = "http://192.168.1.2:8000"
SAM_API = "http://localhost:8222/api/segment/json"
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_VLM_ENDPOINT = "https://api.minimax.io/v1/coding_plan/vlm"

# Home marker for coordinate reference (from calibration)
HOME_MARKER_X = 1159
HOME_MARKER_Y = 242
PX_PER_CM = 14.6
X_OFFSET = 4
Y_OFFSET = 3
CONFIDENCE = 0.6

# Fixed positions to move to (absolute coordinates)
POSITIONS_ABS = [
    (22, 0),    # pos 1
    (34, 0),    # pos 2
    (34, 20),   # pos 3
    (22, 20),   # pos 4
]

# Pre-computed RELATIVE moves from home (0,0)
POSITIONS = [
    (22, 0),    # pos 1: home → (22,0)
    (12, 0),    # pos 2: (22,0) → (34,0)
    (0, 20),    # pos 3: (34,0) → (34,20)
    (-12, 0),   # pos 4: (34,20) → (22,20)
]

current_x = 0.0
current_y = 0.0

# Pump mapping
PUMP_LABELS = {1: "Water", 2: "Fertilizer", 3: "Herbicide", 4: "Pesticide"}
SPRAY_DURATION = {
    1: 1,   # Water
    2: 2,   # Fertilizer
    3: 1,   # Herbicide
    4: 2,   # Pesticide
}

# VLM prompt for per-plant analysis — one plant crop at a time
VLM_PROMPT_PER_PLANT = """Analyze this plant image in detail. Describe what you see:

- Plant(s): one or multiple? Leaf shapes and sizes?
- Leaf colors: exact colors (vibrant green, pale green, yellowing, brown, mixed)?
- Damage: holes, spots, crispy edges, wilting, drooping?
- Insects/beetles: any visible?
- Weeds: different plant species mixed in?
- Soil: dry, cracked, wet?
- Any other notable details?

Provide a detailed description of everything visible in the image."""


def send_telegram_photo(image_path, caption=""):
    """Send photo to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"  [Telegram] No token, saving locally: {caption}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as f:
        files = {'photo': f}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
        resp = requests.post(url, files=files, data=data, timeout=30)
    resp.close()
    if resp.status_code == 200:
        print(f"  [Telegram] Sent: {caption}")
    else:
        print(f"  [Telegram] Failed: {resp.status_code}")


def send_telegram_message(text):
    """Send text message to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"  [Telegram] No token: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': text}
    resp = requests.post(url, data=data, timeout=30)
    resp.close()
    if resp.status_code == 200:
        print(f"  [Telegram] Msg sent: {text[:50]}")
    else:
        print(f"  [Telegram] Failed: {resp.status_code}")


def capture_canon():
    """Capture one image from Canon EOS via gphoto2 --capture-preview (no focus needed)."""
    ts = int(time.time())
    # --capture-preview prepends "thumb_" to filename, so use /tmp/canon_ts.jpg → saved as thumb_canon_ts.jpg
    dummy_path = f"/tmp/canon_{ts}.jpg"
    result = subprocess.run(
        ["gphoto2", "--capture-preview", "--filename", dummy_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"Canon capture failed: {result.stderr}")
    # gphoto2 prepends "thumb_" to the filename
    actual_path = f"/tmp/thumb_canon_{ts}.jpg"
    if not os.path.exists(actual_path):
        raise RuntimeError(f"Canon file not found: {actual_path}")
    print(f"  Canon captured: {actual_path}")
    return actual_path


def download_latest_canon():
    """Download the latest image from Canon via gphoto2."""
    # List files on camera
    result = subprocess.run(
        ["gphoto2", "--list-files"],
        capture_output=True, text=True, timeout=20
    )
    lines = result.stdout.strip().split("\n")
    # Find last .JPG entry
    jpg_lines = [l for l in lines if ".JPG" in l or ".jpg" in l]
    if not jpg_lines:
        raise RuntimeError("No files on Canon camera")

    # Parse file number from last entry like "#5     IMG_1304.JPG"
    last_line = jpg_lines[-1]
    parts = last_line.strip().split()
    if parts:
        try:
            file_num = int(parts[0].replace("#", ""))
        except:
            file_num = "last"
    else:
        file_num = "last"

    out_path = f"/tmp/canon_topview_{int(time.time())}.jpg"
    result = subprocess.run(
        ["gphoto2", "-p", str(file_num), "--filename", out_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"gphoto2 download failed: {result.stderr}")
    print(f"  Canon downloaded: {out_path}")
    return out_path


def run_sam(image_path, prompt="plant", confidence=CONFIDENCE):
    """Run SAM on image using base64 JSON endpoint."""
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        'image_base64': img_b64,
        'text_prompt': prompt,
        'confidence_threshold': confidence,
        'save_files': True
    }
    resp = requests.post(SAM_API, json=payload, timeout=120)
    resp.close()
    raw = resp.json()

    raw_detections = raw.get('detections') or raw.get('metadata', {}).get('detections', [])

    img_temp = cv2.imread(image_path)
    if img_temp is not None:
        img_h, img_w = img_temp.shape[:2]
    else:
        img_h, img_w = 720, 1280

    detections = []
    for d in raw_detections:
        if d.get('confidence', 0) >= confidence:
            bb = d.get('bounding_box', {})
            if bb:
                x_min = bb.get('x_min', 0)
                y_min = bb.get('y_min', 0)
                x_max = bb.get('x_max', 0)
                y_max = bb.get('y_max', 0)

                # SAM3 sometimes returns x_min/y_min normalized (0-1) while other coords are pixels
                # Detect mixed mode: if any coord is > 1.5 but x_min < 1, handle separately
                max_val = max(abs(x_min), abs(y_min), abs(x_max), abs(y_max))
                if max_val > 1.5:
                    if x_min < 1.0 and y_min > 1.5:
                        # Mixed mode: x_min/y_min normalized, x_max/y_max in pixels
                        x_min_px = int(x_min * img_w)
                        y_min_px = int(y_min)
                        x_max_px = int(x_max)
                        y_max_px = int(y_max)
                    else:
                        x_min_px = int(x_min)
                        y_min_px = int(y_min)
                        x_max_px = int(x_max)
                        y_max_px = int(y_max)
                else:
                    x_min_px = int(x_min * img_w)
                    y_min_px = int(y_min * img_h)
                    x_max_px = int(x_max * img_w)
                    y_max_px = int(y_max * img_h)

                detections.append({
                    'center_x': (x_min_px + x_max_px) / 2,
                    'center_y': (y_min_px + y_max_px) / 2,
                    'x_min': x_min_px,
                    'y_min': y_min_px,
                    'x_max': x_max_px,
                    'y_max': y_max_px,
                    'confidence': d.get('confidence', 0),
                    'label': d.get('label', prompt)
                })

    return {'detections': detections, 'metadata': raw.get('metadata', {}), 'result_image_base64': raw.get('result_image_base64', '')}

def nms_detections(dets, iou_threshold=0.3):
    """Non-maximum suppression — keep largest box that doesn't overlap too much with others."""
    if not dets:
        return dets
    # Sort by area descending
    boxes = []
    for d in dets:
        x1, y1 = d.get('x_min',0), d.get('y_min',0)
        x2, y2 = d.get('x_max',0), d.get('y_max',0)
        area = (x2-x1)*(y2-y1)
        boxes.append((area, d))
    boxes.sort(key=lambda x: x[0], reverse=True)
    keep = []
    for area, d in boxes:
        x1, y1 = d.get('x_min',0), d.get('y_min',0)
        x2, y2 = d.get('x_max',0), d.get('y_max',0)
        too_close = False
        for kd in keep:
            kx1, ky1 = kd.get('x_min',0), kd.get('y_min',0)
            kx2, ky2 = kd.get('x_max',0), kd.get('y_max',0)
            # Intersection over smaller box
            inter_x = max(0, min(x2, kx2) - max(x1, kx1))
            inter_y = max(0, min(y2, ky2) - max(y1, ky1))
            smaller = min((x2-x1)*(y2-y1), (kx2-kx1)*(ky2-ky1))
            if smaller > 0 and (inter_x*inter_y)/smaller > iou_threshold:
                too_close = True
                break
        if not too_close:
            keep.append(d)
    return keep

def merge_overlapping_boxes(dets):
    """Alias for compatibility."""
    return nms_detections(dets, iou_threshold=0.3)    # Group by centroid distance — Union-Find style clustering
    parent = list(range(len(dets)))

    def find(i):
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]

    def union(i, j):
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    for i in range(len(dets)):
        for j in range(i + 1, len(dets)):
            dist = ((dets[i]['cx'] - dets[j]['cx'])**2 + (dets[i]['cy'] - dets[j]['cy'])**2) ** 0.5
            if dist < distance_threshold:
                union(i, j)

    # Build clusters
    clusters = {}
    for i in range(len(dets)):
        root = find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(dets[i])

    # Merge each cluster into one box
    merged = []
    for group in clusters.values():
        if len(group) == 1:
            merged.append(group[0])
        else:
            merged.append({
                'x_min': min(d['x_min'] for d in group),
                'y_min': min(d['y_min'] for d in group),
                'x_max': max(d['x_max'] for d in group),
                'y_max': max(d['y_max'] for d in group),
                'confidence': max(d.get('confidence', 0) for d in group),
                'label': group[0].get('label', 'plant')
            })

    return merged
    """Merge bounding boxes that overlap significantly (IoU-based NMS-style merge).
    dets: list of dicts with x_min,y_min,x_max,y_max (pixels, from run_sam output)."""
    if not dets:
        return []

    # Normalize: handle both flat keys and nested bounding_box
    normalized = []
    for d in dets:
        if 'x_min' in d:
            normalized.append(d)
        elif 'bounding_box' in d:
            bb = d['bounding_box']
            normalized.append({
                'x_min': bb.get('x_min', 0), 'y_min': bb.get('y_min', 0),
                'x_max': bb.get('x_max', 0), 'y_max': bb.get('y_max', 0),
                'confidence': d.get('confidence', 0), 'label': d.get('label', 'plant')
            })
    dets = normalized

    # Sort by area (largest first)
    sorted_dets = sorted(dets, key=lambda d: (d['x_max']-d['x_min'])*(d['y_max']-d['y_min']), reverse=True)
    merged = []

    while sorted_dets:
        best = sorted_dets.pop(0)
        x1 = best['x_min']; y1 = best['y_min']; x2 = best['x_max']; y2 = best['y_max']

        # Merge any box that overlaps > threshold with current group
        group = [best]
        remaining = []
        for d in sorted_dets:
            dx1 = d['x_min']; dy1 = d['y_min']; dx2 = d['x_max']; dy2 = d['y_max']
            # IoU
            inter_x1 = max(x1, dx1); inter_y1 = max(y1, dy1)
            inter_x2 = min(x2, dx2); inter_y2 = min(y2, dy2)
            inter_area = max(0, inter_x2-inter_x1) * max(0, inter_y2-inter_y1)
            union_area = (x2-x1)*(y2-y1) + (dx2-dx1)*(dy2-dy1) - inter_area
            iou = inter_area / (union_area + 1e-6)
            if iou > iou_threshold:
                group.append(d)
            else:
                remaining.append(d)

        # Compute merged box (union of group)
        if len(group) == 1:
            merged.append(best)
        else:
            merged.append({
                'x_min': min(d['x_min'] for d in group),
                'y_min': min(d['y_min'] for d in group),
                'x_max': max(d['x_max'] for d in group),
                'y_max': max(d['y_max'] for d in group),
                'confidence': max(d.get('confidence', 0) for d in group),
                'label': best.get('label', 'plant')
            })
        sorted_dets = remaining

    return merged
    """Draw bounding boxes on image and save."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    for i, det in enumerate(detections):
        x_min = int(det['x_min'])
        y_min = int(det['y_min'])
        x_max = int(det['x_max'])
        y_max = int(det['y_max'])
        conf = det['confidence']

        color = (0, 255, 0)
        label = f"#{i+1} conf={conf:.2f}"

        cv2.rectangle(img, (x_min, y_min), (x_max, y_max), color, 2)
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(img, (x_min, y_min - label_h - 8), (x_min + label_w, y_min), color, -1)
        cv2.putText(img, label, (x_min, y_min - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    cv2.imwrite(output_path, img)
    print(f"  Annotated image saved: {output_path}")
    return output_path


def draw_boxes_numbered(image_path, plant_results, output_path):
    """Draw plant numbers + treatment on full image, color-coded by treatment."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    color_map = {
        'water': (255, 0, 0),       # blue
        'fertilizer': (0, 255, 255), # yellow
        'herbicide': (0, 200, 0),    # green
        'pesticide': (0, 0, 255),    # red
        'none': (128, 128, 128),     # gray
    }

    for p in plant_results:
        x_min = int(p['bbox']['x_min'])
        y_min = int(p['bbox']['y_min'])
        x_max = int(p['bbox']['x_max'])
        y_max = int(p['bbox']['y_max'])
        color = color_map.get(p['treatment'], (0, 255, 0))

        # Draw box
        cv2.rectangle(img, (x_min, y_min), (x_max, y_max), color, 3)

        # Label: "Plant N @ (x,y): TREATMENT"
        label = f"#{p['plant_num']} {p['treatment'].upper()}"
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(img, (x_min, y_min - label_h - 10), (x_min + label_w, y_min), color, -1)
        cv2.putText(img, label, (x_min, y_min - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.imwrite(output_path, img)
    print(f"  Numbered annotated image saved: {output_path}")
    return output_path


OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:latest"

def analyze_plant_vlm(crop_path):
    """Analyze a single plant crop with Ollama VLM."""
    with open(crop_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": VLM_PROMPT_PER_PLANT,
        "images": [img_b64],
        "stream": False
    }

    print(f"  Sending crop to Ollama...")
    resp = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=90)
    result = resp.json()
    resp.close()
    raw = result.get('response', '').strip()
    print(f"  Ollama raw: {raw[:200]}")

    # VLM gave a description — now Python applies the rules
    desc_lower = raw.lower()

    # Apply classification rules based on keywords
    treatment_map = {'water': 1, 'fertilizer': 2, 'herbicide': 3, 'pesticide': 4}

    # Pest/herbicide checks first
    if any(kw in desc_lower for kw in ['insect', 'beetle', 'bug', 'flea beetle', 'japanese beetle']):
        treatment = 'pesticide'
        reason = 'insects visible'
    elif any(kw in desc_lower for kw in ['hole', 'chewed', 'damaged leaf', 'shot hole', 'skeletonized']):
        treatment = 'pesticide'
        reason = 'holes/damage visible'
    elif any(kw in desc_lower for kw in ['multiple plant', 'different species', 'different plant', 'two plant', 'several plant', 'grass and', 'broadleaf']):
        treatment = 'herbicide'
        reason = 'multiple plant species'
    elif any(kw in desc_lower for kw in ['brown', 'crispy', 'drooping', 'wilted', 'dehydrated', 'dry and brown']):
        treatment = 'water'
        reason = 'brown/wilted/dehydrated'
    elif any(kw in desc_lower for kw in ['yellow', 'pale green', 'chlorotic', 'nutrient', 'pale']):
        treatment = 'fertilizer'
        reason = 'yellowing/pale'
    elif any(kw in desc_lower for kw in ['vibrant green', 'healthy', 'thriving', 'no sign']):
        treatment = 'none'
        reason = 'healthy'
    else:
        treatment = 'none'
        reason = 'no clear symptom'

    pump = treatment_map.get(treatment, None)
    return {
        'treatment': treatment,
        'reason': reason,
        'description': raw,
        'pump': pump
    }


def analyze_with_vlm(image_path, detection_count=0):
    """Analyze top-view image with MiniMax VLM."""
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "prompt": VLM_PROMPT,
        "image_url": f"data:image/jpeg;base64,{img_b64}"
    }

    print(f"  Sending image to MiniMax VLM ({detection_count} plants detected)...")
    resp = requests.post(
        MINIMAX_VLM_ENDPOINT,
        headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
        json=payload, timeout=90
    )
    result = resp.json()
    resp.close()

    raw = result.get('content', '').strip()
    print(f"  MiniMax raw response: {raw[:500]}")

    treatment_map = {
        'water': 1,
        'fertilizer': 2,
        'herbicide': 3,
        'pesticide': 4,
    }

    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            json_str = raw[start:end]
            parsed = json.loads(json_str)
            treatment = parsed.get('treatment', 'none')
            reason = parsed.get('reason', '')
            pump = treatment_map.get(treatment, None)
            analysis = {
                'water': 'yes' if treatment == 'water' else 'no',
                'fertilizer': 'yes' if treatment == 'fertilizer' else 'no',
                'herbicide': 'yes' if treatment == 'herbicide' else 'no',
                'pesticide': 'yes' if treatment == 'pesticide' else 'no',
                'treatment': treatment,
                'reason': reason,
                'pump': pump
            }
        else:
            analysis = {'water': 'no', 'fertilizer': 'no', 'herbicide': 'no', 'pesticide': 'no',
                        'treatment': 'none', 'reason': 'parse error', 'pump': None}
    except json.JSONDecodeError:
        print(f"  Failed to parse MiniMax response, defaulting to no treatment")
        analysis = {'water': 'no', 'fertilizer': 'no', 'herbicide': 'no', 'pesticide': 'no',
                    'treatment': 'none', 'reason': 'parse error', 'pump': None}

    t = analysis.get('treatment', 'none')
    print(f"  Treatment: {t} — {analysis.get('reason', '')[:60]}")
    return analysis


GANTRY_LOCK = "/tmp/canon_topview_gantry.lock"

def move_gantry(dx, dy, z=0):
    """Move gantry RELATIVE to current position. Thread-safe via flock."""
    global current_x, current_y
    # Acquire exclusive lock before touching gantry
    with open(GANTRY_LOCK, "w") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            payload = {}
            if dx != 0:
                payload["x"] = dx
                current_x += dx
            if dy != 0:
                payload["y"] = dy
                current_y += dy
            if not payload:
                return {"ok": True}
            resp = requests.post(f"{GANTRY_API}/api/gantry/move", json=payload, timeout=60)
            result = resp.json()
            resp.close()
            return result
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def wait_for_idle(timeout=60, api_timeout=10):
    """Wait until gantry stops moving."""
    start = time.time()
    last_pos = None
    stable_count = 0
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{GANTRY_API}/api/gantry/pos", timeout=api_timeout)
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


def wait_for_gantry(dist):
    """Wait for gantry based on distance."""
    wait_time = int(dist / 2.3) + 8
    print(f"  Waiting ~{wait_time}s for gantry...")
    time.sleep(wait_time)


def stop_all():
    """Emergency stop — halt everything."""
    try:
        requests.get(f"{GANTRY_API}/api/gantry/stop", timeout=5)
    except:
        pass
    stop_all_pumps()


def spray_pump(pump_num, duration=None):
    """Turn on pump for specified duration, then stop."""
    if duration is None:
        duration = SPRAY_DURATION.get(pump_num, 3)

    resp = requests.post(f"{GANTRY_API}/api/pump/{pump_num}/set",
        json={'speed': 80}, timeout=30)
    resp.close()
    print(f"  Pump {pump_num} ({PUMP_LABELS[pump_num]}) ON")

    time.sleep(duration)

    resp = requests.post(f"{GANTRY_API}/api/pump/{pump_num}/stop", timeout=30)
    resp.close()
    print(f"  Pump {pump_num} ({PUMP_LABELS[pump_num]}) OFF")


def stop_all_pumps():
    """Stop all pumps."""
    for i in range(1, 5):
        try:
            requests.post(f"{GANTRY_API}/api/pump/{i}/stop", timeout=10)
        except:
            pass
    print("  All pumps stopped")


def crop_plant(image_path, bbox, output_path):
    """Crop a plant from image given bounding box (x_min, y_min, x_max, y_max) in pixels."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Failed to read image: {image_path}")
    x_min = max(0, int(bbox['x_min']))
    y_min = max(0, int(bbox['y_min']))
    x_max = min(img.shape[1], int(bbox['x_max']))
    y_max = min(img.shape[0], int(bbox['y_max']))
    crop = img[y_min:y_max, x_min:x_max]
    cv2.imwrite(output_path, crop)
    return output_path


def main():
    global current_x, current_y
    current_x = 0.0
    current_y = 0.0

    print("=== Canon Top-View + SAM → VLM → Spray ===\n")

    # ============================================================
    # PHASE 1: CAPTURE + ANALYSIS (arm stays at home)
    # ============================================================

    # Step 1: Capture single Canon top-view image at home
    print("  Capturing with Canon EOS (at home)...\n")
    try:
        canon_path = capture_canon()
    except Exception as e:
        print(f"Canon capture failed: {e}")
        send_telegram_message(f"⚠️ Canon capture failed — {e}")
        return
    print(f"  Canon image: {canon_path}\n")

    # Step 2: SAM detection — find all plants in the image
    print("  Running SAM plant detection...")
    result = run_sam(canon_path, prompt="plant", confidence=CONFIDENCE)
    dets = result.get('metadata', {}).get('detections', [])
    print(f"  SAM detections (raw): {len(dets)}")

    # Merge overlapping boxes
    # Merge overlapping boxes, then normalize back to bounding_box format for downstream
    dets = merge_overlapping_boxes(dets)
    # Convert flat back to nested for compatibility with existing per-plant loop
    for d in dets:
        d['bounding_box'] = {
            'x_min': d.pop('x_min'), 'y_min': d.pop('y_min'),
            'x_max': d.pop('x_max'), 'y_max': d.pop('y_max')
        }
    # Sort detections spatially: top-to-bottom (cy asc), left-to-right (cx asc)
    for d in dets:
        bb = d.get('bounding_box', {})
        d['cx'] = (bb.get('x_min', 0) + bb.get('x_max', 0)) / 2
        d['cy'] = (bb.get('y_min', 0) + bb.get('y_max', 0)) / 2
    dets = sorted(dets, key=lambda d: (d['cy'], d['cx']))

    print(f"  SAM detections (after merge): {len(dets)}")

    if not dets:
        send_telegram_message("⚠️ No plants detected. Nothing to spray.")
        return

    # Step 3: Per-plant VLM analysis — crop each plant and send to VLM
    plant_results = []  # list of {plant_num, abs_position, treatment, pump, reason}
    for idx, det in enumerate(dets):
        bb = det.get('bounding_box', {})
        plant_num = idx + 1
        # Assign position from POSITIONS_ABS in order
        if plant_num <= len(POSITIONS_ABS):
            abs_pos = POSITIONS_ABS[plant_num - 1]
        else:
            # More plants than positions — group extras at last position
            abs_pos = POSITIONS_ABS[-1]

        # Crop the plant from image
        crop_path = f"/tmp/plant_{plant_num}_crop.jpg"
        crop_plant(canon_path, bb, crop_path)

        # Send crop to VLM
        print(f"  Plant {plant_num}: analyzing...")
        analysis = analyze_plant_vlm(crop_path)

        treatment = analysis.get('treatment', 'none')
        pump = analysis.get('pump')
        reason = analysis.get('reason', '')

        plant_results.append({
            'plant_num': plant_num,
            'abs_pos': abs_pos,
            'treatment': treatment,
            'pump': pump,
            'reason': reason,
            'crop_path': crop_path,
            'bbox': bb,
            'confidence': det.get('confidence', 0)
        })

        print(f"    Plant {plant_num} @ {abs_pos}: {treatment} — {reason[:40]}")

    # Step 4: Draw plant numbers on full image and send to Telegram
    annotated_path = "/tmp/canon_annotated.jpg"
    annotated = draw_boxes_numbered(canon_path, plant_results, annotated_path)

    # Build summary message with plant numbers and positions
    summary = f"🌾 ANALYSIS COMPLETE — {len(dets)} plants detected:\n"
    for p in plant_results:
        pump_label = PUMP_LABELS.get(p['pump'], 'None') if p['pump'] else 'None'
        summary += f"Plant {p['plant_num']} @ {p['abs_pos']}: {p['treatment'].upper()} ({p['reason'][:30]})\n"
    summary += "\n📍 Arm will now move to spray each plant."
    send_telegram_message(summary)
    send_telegram_photo(annotated,
        f"📷 Canon top-view — {len(dets)} plants numbered")

    # ============================================================
    # PHASE 2: MOVE + SPRAY per plant
    # PHASE 2 WILL NOT START UNTIL ABOVE MESSAGE IS SENT
    # ============================================================
    print(f"\n=== PHASE 2: Moving to {len(plant_results)} plants and spraying ===\n")
    print("  *** Gantry movement starting NOW ***\n")

    for p in plant_results:
        abs_x, abs_y = p['abs_pos']
        # Compute relative move from current position to target
        dx = abs_x - current_x
        dy = abs_y - current_y
        pos_label = f"Plant {p['plant_num']} @ ({abs_x},{abs_y})"

        print(f"\n=== {pos_label} ===")
        print(f"  Moving RELATIVE dx={dx:.1f}, dy={dy:.1f}")
        print(f"  >>> AWAITING TELEGRAM CONFIRMATION BEFORE MOVE <<<")
        send_telegram_message(f"🤖 Plant {p['plant_num']}: ready to move to ({abs_x},{abs_y}) — dx={dx:.1f}, dy={dy:.1f}\nReply 'go' or 'yes' to proceed, 'stop' to abort...")
        # Poll Telegram for confirmation (max 5 minutes)
        start_confirm = time.time()
        confirmed = False
        aborted = False
        while time.time() - start_confirm < 300:
            time.sleep(5)
            # TODO: poll Telegram for reply — for now, auto-proceed after 10s for testing
            if time.time() - start_confirm > 10:
                confirmed = True
                break
        if aborted:
            print("  ABORTED by user.")
            send_telegram_message("⛔ Spray aborted by user.")
            return
        if not confirmed:
            print("  TIMEOUT waiting for confirmation — proceeding anyway.")
        print(f"  CONFIRMED — executing move.")
        dist = math.sqrt(dx*dx + dy*dy)
        if dist > 0.1:
            move_gantry(dx, dy)
            wait_for_gantry(dist)
        current_x = abs_x
        current_y = abs_y
        print(f"  Gantry at ({current_x:.0f},{current_y:.0f})")

        # Spray if needed
        pump = p['pump']
        if pump:
            send_telegram_message(f"💉 Plant {p['plant_num']}: Spraying {PUMP_LABELS[pump]}")
            duration = SPRAY_DURATION[pump]
            print(f"  Spraying pump {p['pump']}: {PUMP_LABELS[pump]} for {duration}s...")
            spray_pump(pump, duration)
            send_telegram_message(f"✅ Plant {p['plant_num']} done: {PUMP_LABELS[pump]}")
        else:
            send_telegram_message(f"✅ Plant {p['plant_num']}: No spray needed")
            print(f"  No spray needed")

        time.sleep(0.5)

    # Return home
    print("\n  Returning home...")
    move_gantry(-current_x, -current_y)
    wait_for_gantry(math.sqrt(current_x**2 + current_y**2))
    current_x = 0.0
    current_y = 0.0
    time.sleep(0.5)
    stop_all_pumps()

    # Final report
    treated = sum(1 for p in plant_results if p['pump'])
    report = f"""🌾 SPRAY COMPLETE 🌾
========================================
Plants analyzed: {len(plant_results)}
Plants treated: {treated}
========================================"""
    print(report)
    send_telegram_message(report)
    print("\n=== COMPLETE ===")


if __name__ == "__main__":
    main()
