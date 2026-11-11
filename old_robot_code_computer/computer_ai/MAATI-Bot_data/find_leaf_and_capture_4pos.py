#!/usr/bin/env python3
"""
Find plants using SAM on video1, merge overlapping bounding boxes.
Instead of moving to detected plant positions, move to 4 FIXED positions.
At each fixed position: capture with video0, analyze with MiniMax VLM, spray appropriate chemical.
4 pumps: 1=water, 2=fertilizer, 3=herbicide, 4=pesticide
"""
import cv2
import requests
import base64
import os
import math
import json
import time

# Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "7674508568"
CAMERA_SERVER = "http://localhost:8225"
VIDEO1_DEVICE = "/dev/video1"
VIDEO0_USB_INDEX = 0
VIDEO1_USB_INDEX = 1
SAM_API = "http://localhost:8222/api/segment/json"
GANTRY_API = "http://192.168.1.2:8000"
OLLAMA_API = "http://localhost:11434/api/generate"
HOME_MARKER_X = 1159
HOME_MARKER_Y = 242
PX_PER_CM = 14.6
X_OFFSET = 4
Y_OFFSET = 3
CONFIDENCE = 0.3

# Fixed positions to scan (replaces detected plant positions)
POSITIONS = [
    (22, 0),    # pos 1
    (12, 0),    # pos 2: x to 34
    (0, 20),    # pos 3: y to 20
    (-12, 0),   # pos 4: x back to 22
]  # home handled separately at end
current_x = 0.0
current_y = 0.0

# Pump mapping
PUMP_WATER = 1
PUMP_FERTILIZER = 2
PUMP_HERBICIDE = 3
PUMP_PESTICIDE = 4
PUMP_LABELS = {1: "Water", 2: "Fertilizer", 3: "Herbicide", 4: "Pesticide"}

# Spray duration per chemical (seconds)
SPRAY_DURATION = {
    1: 3,   # Water
    2: 5,   # Fertilizer
    3: 4,   # Herbicide
    4: 4,   # Pesticide
}

# Ollama prompt for plant health analysis
OLLAMA_PROMPT = """Look at this plant image and answer the following FOUR questions:
1. Does the plant show YELLOWING or PALE leaves? (yes/no)
2. Does the plant show DROOPING or WILTING? (yes/no)
3. Does the plant show CHEWED edges, HOLES in leaves, or INSECTS present? (yes/no)
4. Does the plant show MIXED WEEDS (grass AND broadleaf growing together)? (yes/no)

IMPORTANT: Only choose ONE treatment based on the MOST VISIBLE problem:
- If DROOPING/WILTING → only water
- If YELLOWING/PALE but not drooping → only fertilizer
- If CHEWED edges/INSECTS → only pesticide
- If MIXED WEEDS (no other urgent issue) → only herbicide

Answer in JSON format with EXACTLY ONE treatment:
{"treatment": "water" OR "fertilizer" OR "herbicide" OR "pesticide" OR "none", "reason": "brief reason why this treatment and not others"}"""

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_VLM_ENDPOINT = "https://api.minimax.io/v1/coding_plan/vlm"


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


def capture_camera(device, width=1280, height=720):
    """Capture frame from V4L2 camera."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FORMAT, cv2.VideoWriter_fourcc('M','J','P','G'))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"Failed to capture from {device}")
    return frame


def capture_video0():
    """Capture from video0 via camera server with brightness boost."""
    resp = requests.get(f"{CAMERA_SERVER}/usb_capture?usb_index={VIDEO0_USB_INDEX}", timeout=30)
    resp.close()
    d = resp.json()
    if not d.get('success'):
        raise RuntimeError(f"Camera server failed: {d.get('error')}")
    path = d['file_path']
    frame = cv2.imread(path)
    if frame is None:
        raise RuntimeError(f"Failed to read image: {path}")
    boosted = cv2.convertScaleAbs(frame, alpha=1.3, beta=30)
    return boosted


def capture_video1():
    """Capture from video1 (SAM cam) via camera server."""
    resp = requests.get(f"{CAMERA_SERVER}/usb_capture?usb_index={VIDEO1_USB_INDEX}", timeout=30)
    resp.close()
    d = resp.json()
    if not d.get('success'):
        raise RuntimeError(f"Camera server failed: {d.get('error')}")
    path = d['file_path']
    frame = cv2.imread(path)
    if frame is None:
        raise RuntimeError(f"Failed to read image: {path}")
    return frame


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
                
                max_val = max(abs(x_min), abs(y_min), abs(x_max), abs(y_max))
                if max_val > 1.5:
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


def analyze_with_ollama(image_path):
    """Analyze plant health using MiniMax VLM."""
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = OLLAMA_PROMPT
    
    payload = {
        "prompt": prompt,
        "image_url": f"data:image/jpeg;base64,{img_b64}"
    }
    
    print("    Sending image to MiniMax VLM...")
    resp = requests.post(
        MINIMAX_VLM_ENDPOINT,
        headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
        json=payload, timeout=90
    )
    result = resp.json()
    resp.close()
    
    raw = result.get('content', '').strip()
    print(f"    MiniMax raw response: {raw[:500]}")
    
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
            analysis = {'water': 'no', 'fertilizer': 'no', 'herbicide': 'no', 'pesticide': 'no', 'treatment': 'none', 'reason': 'parse error', 'pump': None}
    except json.JSONDecodeError:
        print(f"    Failed to parse MiniMax response, defaulting to no treatment")
        analysis = {'water': 'no', 'fertilizer': 'no', 'herbicide': 'no', 'pesticide': 'no', 'treatment': 'none', 'reason': 'parse error', 'pump': None}
    
    t = analysis.get('treatment', 'none')
    print(f"    Single treatment: {t} — {analysis.get('reason', '')[:50]}")
    return analysis


def merge_overlapping_boxes(dets):
    """Merge any bounding boxes that overlap."""
    if not dets:
        return []
    
    boxes = []
    for det in dets:
        bb = det.get('bounding_box', {})
        x_min = bb.get('x_min', 0)
        y_min = bb.get('y_min', 0)
        x_max = bb.get('x_max', 0)
        y_max = bb.get('y_max', 0)
        conf = det.get('confidence', 0)
        boxes.append({
            'x_min': x_min, 'y_min': y_min,
            'x_max': x_max, 'y_max': y_max,
            'cx': (x_min + x_max) / 2,
            'cy': (y_min + y_max) / 2,
            'conf': conf
        })
    
    merged = []
    used = set()
    
    for i, box in enumerate(boxes):
        if i in used:
            continue
        
        group = [box]
        used.add(i)
        
        for j, other in enumerate(boxes):
            if j in used:
                continue
            inter_x_min = max(box['x_min'], other['x_min'])
            inter_y_min = max(box['y_min'], other['y_min'])
            inter_x_max = min(box['x_max'], other['x_max'])
            inter_y_max = min(box['y_max'], other['y_max'])
            
            if inter_x_max > inter_x_min and inter_y_max > inter_y_min:
                group.append(other)
                used.add(j)
        
        all_x_min = min(b['x_min'] for b in group)
        all_y_min = min(b['y_min'] for b in group)
        all_x_max = max(b['x_max'] for b in group)
        all_y_max = max(b['y_max'] for b in group)
        avg_cx = sum(b['cx'] for b in group) / len(group)
        avg_cy = sum(b['cy'] for b in group) / len(group)
        max_conf = max(b['conf'] for b in group)
        
        merged.append({
            'x_min': all_x_min, 'y_min': all_y_min,
            'x_max': all_x_max, 'y_max': all_y_max,
            'cx': avg_cx, 'cy': avg_cy,
            'conf': max_conf,
            'count': len(group)
        })
    
    return merged


# Lag/slip compensation
LAG_THRESHOLD_CM = 10
LAG_COMPENSATION_PCT = 0.05

def calc_move(plant_x, plant_y):
    """Calculate gantry move from plant position. Always round UP."""
    dx = math.ceil((HOME_MARKER_X - plant_x) / PX_PER_CM) + X_OFFSET
    dy = math.ceil((plant_y - HOME_MARKER_Y) / PX_PER_CM) + Y_OFFSET
    
    dist = math.sqrt(dx*dx + dy*dy)
    if dist > LAG_THRESHOLD_CM:
        extra_cm = (dist - LAG_THRESHOLD_CM) * LAG_COMPENSATION_PCT
        if dx != 0:
            dx = math.ceil(dx + (dx / dist) * extra_cm)
        if dy != 0:
            dy = math.ceil(dy + (dy / dist) * extra_cm)
    
    return dx, dy


def move_gantry(dx, dy, z=0):
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
        return {"ok": True}
    resp = requests.post(f"{GANTRY_API}/api/gantry/move", json=payload, timeout=60)
    result = resp.json()
    resp.close()
    return result


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
    print(f"    Waiting ~{wait_time}s for gantry...")
    time.sleep(wait_time)


def spray_pump(pump_num, duration=None):
    """Turn on pump for specified duration, then stop."""
    if duration is None:
        duration = SPRAY_DURATION.get(pump_num, 3)
    
    resp = requests.post(f"{GANTRY_API}/api/pump/{pump_num}/set",
        json={'speed': 80}, timeout=30)
    resp.close()
    print(f"    Pump {pump_num} ({PUMP_LABELS[pump_num]}) ON")
    
    time.sleep(duration)
    
    resp = requests.post(f"{GANTRY_API}/api/pump/{pump_num}/stop", timeout=30)
    resp.close()
    print(f"    Pump {pump_num} ({PUMP_LABELS[pump_num]}) OFF")


def stop_all_pumps():
    """Stop all pumps."""
    for i in range(1, 5):
        try:
            requests.post(f"{GANTRY_API}/api/pump/{i}/stop", timeout=10)
        except:
            pass
    print("  All pumps stopped")


def draw_merged_boxes(frame, merged_boxes, analysis_results=None):
    """Draw merged bounding boxes + analysis labels on image."""
    img = frame.copy()
    
    for i, box in enumerate(merged_boxes):
        x_min = int(box['x_min'])
        y_min = int(box['y_min'])
        x_max = int(box['x_max'])
        y_max = int(box['y_max'])
        conf = box['conf']
        
        color = (0, 255, 0)
        label = f"#{i+1} conf={conf:.2f}"
        
        if analysis_results and i < len(analysis_results):
            ar = analysis_results[i]
            chem = ar.get('chemical', 'unknown')
            
            if chem == "healthy":
                color = (0, 255, 0)
            elif chem == "water":
                color = (255, 180, 0)
            elif chem == "fertilizer":
                color = (0, 200, 255)
            elif chem == "herbicide":
                color = (0, 100, 255)
            elif chem == "pesticide":
                color = (0, 0, 255)
            else:
                color = (200, 200, 200)
            
            reason = ar.get('reason', '')[:30]
            label = f"#{i+1} {chem.upper()} {reason}"
        
        cv2.rectangle(img, (x_min, y_min), (x_max, y_max), color, 2)
        cv2.putText(img, label, (x_min, y_min - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        cx, cy = int(box['cx']), int(box['cy'])
        cv2.circle(img, (cx, cy), 5, color, -1)
    
    return img


def generate_report(all_results):
    """Generate final summary report."""
    report = []
    report.append("🌾 PLANT HEALTH REPORT 🌾")
    report.append("=" * 40)
    
    total = len(all_results)
    total_water = sum(1 for r in all_results if r.get('treatment') == 'water')
    total_fert = sum(1 for r in all_results if r.get('treatment') == 'fertilizer')
    total_herb = sum(1 for r in all_results if r.get('treatment') == 'herbicide')
    total_pest = sum(1 for r in all_results if r.get('treatment') == 'pesticide')
    plants_treated = sum(1 for r in all_results if r.get('treatment') != 'none' and r.get('treatment') is not None)
    
    report.append(f"\nTotal positions scanned: {total}")
    report.append(f"  💧 Water:    {total_water}")
    report.append(f"  🧪 Fertilizer: {total_fert}")
    report.append(f"  🌿 Herbicide: {total_herb}")
    report.append(f"  🐛 Pesticide: {total_pest}")
    report.append(f"\nPositions needing treatment: {plants_treated}/{total}")
    
    report.append("\n" + "=" * 40)
    report.append("DETAILED ASSESSMENT")
    report.append("=" * 40)
    
    for i, r in enumerate(all_results):
        plant_num = i + 1
        treatment = r.get('treatment', 'none')
        reason = r.get('reason', 'N/A')
        pump = r.get('pump')
        
        report.append(f"\nPosition {plant_num}:")
        report.append(f"  Treatment: {treatment.upper()}")
        report.append(f"  Reason: {reason}")
        if pump:
            names = PUMP_LABELS[pump]
            report.append(f"  Action: ✅ Sprayed {names}")
        else:
            report.append(f"  Action: ✅ No spray needed")
    
    report.append("\n" + "=" * 40)
    if plants_treated > 0:
        report.append(f"{plants_treated} of {total} positions received treatment.")
    else:
        report.append("All plants look healthy! 🌱")
    
    report_text = "\n".join(report)
    return report_text, {"treated": plants_treated, "total": total}


def main():
    global current_x, current_y
    current_x = 0.0
    current_y = 0.0
    
    print("=== Find Plants (SAM) → 4 Fixed Positions → Analyze & Spray ===\n")
    
    # Step 1: Capture from video1 for SAM detection
    print("[1/7] Capturing from video1 for plant detection...")
    frame = capture_camera(VIDEO1_DEVICE)
    sam_input = "/tmp/v1_for_sam.jpg"
    cv2.imwrite(sam_input, frame)
    print(f"  Saved: {frame.shape[1]}x{frame.shape[0]}")
    
    # Step 2: Run SAM with "plant" prompt
    print("\n[2/7] Running SAM (plant detection)...")
    result = run_sam(sam_input, prompt="plant", confidence=CONFIDENCE)
    dets = result.get('metadata', {}).get('detections', [])
    print(f"  Detections: {len(dets)}")
    
    # Step 3: Merge overlapping bounding boxes
    print("\n[3/7] Merging overlapping bounding boxes...")
    merged = merge_overlapping_boxes(dets)
    print(f"  Merged into {len(merged)} plant groups")
    
    for i, box in enumerate(merged):
        print(f"  Plant {i+1}: center=({box['cx']:.0f},{box['cy']:.0f}), conf={box['conf']:.3f}, count={box['count']}")
    
    if not merged:
        send_telegram_message("❌ No plants detected. Please check camera.")
    
    # Draw merged boxes
    annotated = draw_merged_boxes(frame, merged)
    cv2.imwrite('/tmp/sam_merged_result.jpg', annotated)
    send_telegram_photo('/tmp/sam_merged_result.jpg',
        f"🌱 SAM: {len(dets)} detections → {len(merged)} plants")
    
    # Step 4: Process each FIXED POSITION (not detected plants)
    print(f"\n[4/7] Processing {len(POSITIONS)} fixed positions...")
    all_analysis_results = []
    all_capture_paths = []
    
    for i, (dx, dy) in enumerate(POSITIONS):
        pos_label = f"Fixed Pos {i+1}"
        print(f"\n  === {pos_label} ===")
        print(f"  Moving RELATIVE dx={dx}, dy={dy}")
        
        dist = math.sqrt(dx*dx + dy*dy)
        
        # Move to fixed position
        print(f"  Moving to position...")
        move_gantry(dx, dy)
        wait_for_gantry(dist)
        print(f"  Waiting for camera to settle...")
        time.sleep(3)
        
        # Capture with video0
        print(f"  Capturing with video0...")
        v0_frame = capture_video0()
        capture_path = f"/tmp/plant_{i+1}_capture.jpg"
        cv2.imwrite(capture_path, v0_frame)
        all_capture_paths.append(capture_path)
        print(f"  Saved: {capture_path}")
        
        # Send capture to Telegram
        send_telegram_photo(capture_path,
            f"🌿 {pos_label} ({current_x:.0f},{current_y:.0f})")
        
        # Step 5: Analyze with MiniMax VLM
        print(f"\n  [5/7] Analyzing with MiniMax VLM...")
        analysis = analyze_with_ollama(capture_path)
        all_analysis_results.append(analysis)
        
        treatment = analysis.get('treatment', 'none')
        reason = analysis.get('reason', '')
        pump = analysis.get('pump')
        
        # Send analysis to Telegram
        scores_msg = f"🔍 {pos_label}:\n  Treatment: {treatment.upper()}\n  Reason: {reason}"
        if pump:
            scores_msg += f"\n  💉 Spraying: {PUMP_LABELS[pump]}"
        else:
            scores_msg += f"\n  ✅ No spray needed"
        send_telegram_message(scores_msg)
        
        # Step 6: Spray single pump if needed
        if pump:
            duration = SPRAY_DURATION[pump]
            print(f"\n  [6/7] Spraying pump {pump}: {PUMP_LABELS[pump]} for {duration}s...")
            spray_pump(pump, duration)
            send_telegram_message(f"✅ {pos_label} done: {PUMP_LABELS[pump]}")
        else:
            print(f"  [6/7] No spray needed")
            send_telegram_message(f"ℹ️ {pos_label}: No spray needed")
        
        time.sleep(0.5)
        print(f"  {pos_label} complete\n")
    
    # Return home (no capture/spray at home position)
    print("\n  Returning home...")
    move_gantry(-22, -20)
    wait_for_gantry(math.sqrt(22**2 + 20**2))
    time.sleep(0.5)
    
    # Stop all pumps as safety
    stop_all_pumps()
    
    # Step 7: Generate final report
    print("\n[7/7] Generating final report...")
    report_text, counts = generate_report(all_analysis_results)
    print("\n" + report_text)
    
    # Send all images to Telegram
    print("\nSending all images to Telegram...")
    for i, path in enumerate(all_capture_paths):
        ar = all_analysis_results[i] if i < len(all_analysis_results) else {}
        caption = f"Plant {i+1}/{len(all_capture_paths)}"
        send_telegram_photo(path, caption)
    
    # Send annotated result
    annotated_final = draw_merged_boxes(frame, merged, all_analysis_results)
    cv2.imwrite('/tmp/final_annotated_result.jpg', annotated_final)
    send_telegram_photo('/tmp/final_annotated_result.jpg',
        "🗺️ SAM detections with treatment decisions")
    
    # Send final report
    send_telegram_message(report_text)
    
    print("\n=== COMPLETE ===")
    print(f"Fixed positions scanned: {len(POSITIONS)}")
    print(f"SAM detections: {len(merged)} plants found")
    print(f"Report sent to Telegram.")


if __name__ == "__main__":
    main()