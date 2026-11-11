#!/usr/bin/env python3
"""
Find plants using SAM on video1, merge overlapping bounding boxes,
move to each plant (with y+5 offset), capture with video0, 
analyze with Ollama Gemma, spray appropriate chemical, return home.
4 pumps: 1=water, 2=fertilizer, 3=herbicide, 4=pesticide
"""
import cv2
import requests
import base64
import shutil
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
CONFIDENCE = 0.4


# Pump mapping
PUMP_WATER = 1
PUMP_FERTILIZER = 2
PUMP_HERBICIDE = 3
PUMP_PESTICIDE = 4
PUMP_LABELS = {1: "Water", 2: "Fertilizer", 3: "Herbicide", 4: "Pesticide"}

# Spray duration per chemical (seconds)
SPRAY_DURATION = {
    1: 3,   # Water - short rinse
    2: 5,   # Fertilizer
    3: 4,   # Herbicide
    4: 4,   # Pesticide
}

# Ollama prompt for plant health analysis
OLLAMA_PROMPT = """Look at this plant image and answer:
1. Do you see YELLOWING or PALE leaves? (yes/no)
2. Do you see DROOPING or WILTING? (yes/no)
3. Do you see HOLES, CHEWED edges, or INSECTS? (yes/no)
4. Do you see MIXED WEEDS (grass + broadleaf together)? (yes/no)

Answer JSON exactly: {"water":"yes or no","fertilizer":"yes or no","herbicide":"yes or no","pesticide":"yes or no","reason":"brief reason"}"""


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
    # Boost brightness: alpha=1.3 (contrast), beta=30 (brightness add)
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
    
    # SAM API v2: detections moved to metadata['detections']
    raw_detections = raw.get('detections') or raw.get('metadata', {}).get('detections', [])
    
    # Get image dimensions for coordinate normalization
    import cv2
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
                
                # Detect if coords are normalized (0-1 range) or pixels
                # Use the larger dimension to decide - if any value > 1.0 it's pixels
                max_val = max(abs(x_min), abs(y_min), abs(x_max), abs(y_max))
                if max_val > 1.5:
                    # Already in pixel coordinates
                    x_min_px = int(x_min)
                    y_min_px = int(y_min)
                    x_max_px = int(x_max)
                    y_max_px = int(y_max)
                else:
                    # Normalized 0-1, convert to image pixels
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
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_VLM_ENDPOINT = "https://api.minimax.io/v1/coding_plan/vlm"

def analyze_with_ollama(image_path):
    """Analyze plant health using MiniMax VLM (better accuracy than Ollama Gemma)."""
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
    
    # Parse JSON from response
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            json_str = raw[start:end]
            analysis = json.loads(json_str)
        else:
            analysis = {"water": "no", "fertilizer": "no", "herbicide": "no", "pesticide": "no", "reason": "parse error"}
    except json.JSONDecodeError:
        print(f"    Failed to parse MiniMax response, defaulting to no treatment")
        analysis = {"water": "no", "fertilizer": "no", "herbicide": "no", "pesticide": "no", "reason": "parse error"}
    
    w = analysis.get('water','no')
    f = analysis.get('fertilizer','no')
    h = analysis.get('herbicide','no')
    p = analysis.get('pesticide','no')
    print(f"    Result — water:{w}, fertilizer:{f}, herbicide:{h}, pesticide:{p}")
    return analysis

def merge_overlapping_boxes(dets):
    """
    Merge any bounding boxes that overlap (intersect at all).
    Returns list of merged boxes with averaged center and max confidence.
    """
    if not dets:
        return []
    
    boxes = []
    for det in dets:
        bb = det['bounding_box']
        x_min = bb['x_min']
        y_min = bb['y_min']
        x_max = bb['x_max']
        y_max = bb['y_max']
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


# Lag/slip compensation: further moves lag more (add extra % per cm over threshold)
LAG_THRESHOLD_CM = 10
LAG_COMPENSATION_PCT = 0.05

def calc_move(plant_x, plant_y):
    """Calculate gantry move from plant position. Always round UP."""
    dx = math.ceil((HOME_MARKER_X - plant_x) / PX_PER_CM) + X_OFFSET
    dy = math.ceil((plant_y - HOME_MARKER_Y) / PX_PER_CM) + Y_OFFSET
    
    # Lag compensation: further moves undershoot more
    dist = math.sqrt(dx*dx + dy*dy)
    if dist > LAG_THRESHOLD_CM:
        extra_cm = (dist - LAG_THRESHOLD_CM) * LAG_COMPENSATION_PCT
        if dx != 0:
            dx = math.ceil(dx + (dx / dist) * extra_cm)
        if dy != 0:
            dy = math.ceil(dy + (dy / dist) * extra_cm)
    
    return dx, dy


def move_gantry(x, y, z=0):
    """Move gantry to position (relative move)."""
    resp = requests.post(f"{GANTRY_API}/api/gantry/move",
        json={'x': x, 'y': y, 'z': z}, timeout=60)
    result = resp.json()
    resp.close()
    return result


def wait_for_gantry(timeout=60):
    """Wait for gantry to finish moving using fixed delay."""
    time.sleep(timeout)
    return True


def spray_pump(pump_num, duration=None):
    """Turn on pump for specified duration, then stop."""
    if duration is None:
        duration = SPRAY_DURATION.get(pump_num, 3)
    
    # Turn on pump
    resp = requests.post(f"{GANTRY_API}/api/pump/{pump_num}/set",
        json={'speed': 80}, timeout=30)
    resp.close()
    print(f"    Pump {pump_num} ({PUMP_LABELS[pump_num]}) ON")
    
    # Wait for spray duration
    time.sleep(duration)
    
    # Turn off pump
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


def chemical_to_pump(chemical):
    """Convert chemical name to pump number."""
    mapping = {
        "water": PUMP_WATER,
        "fertilizer": PUMP_FERTILIZER,
        "herbicide": PUMP_HERBICIDE,
        "pesticide": PUMP_PESTICIDE,
        "healthy": None,
    }
    return mapping.get(chemical.lower(), None)


def draw_merged_boxes(frame, merged_boxes, analysis_results=None):
    """Draw merged bounding boxes + analysis labels on image."""
    img = frame.copy()
    
    for i, box in enumerate(merged_boxes):
        x_min = int(box['x_min'])
        y_min = int(box['y_min'])
        x_max = int(box['x_max'])
        y_max = int(box['y_max'])
        conf = box['conf']
        count = box.get('count', 1)
        
        # Get analysis if available
        color = (0, 255, 0)  # Default green
        label = f"#{i+1} conf={conf:.2f}"
        
        if analysis_results and i < len(analysis_results):
            ar = analysis_results[i]
            chem = ar.get('chemical', 'unknown')
            severity = ar.get('severity', 'low')
            reason = ar.get('reason', '')[:30]
            
            if chem == "healthy":
                color = (0, 255, 0)   # Green
            elif chem == "water":
                color = (255, 180, 0) # Orange
            elif chem == "fertilizer":
                color = (0, 200, 255) # Cyan
            elif chem == "herbicide":
                color = (0, 100, 255) # Blue
            elif chem == "pesticide":
                color = (0, 0, 255)    # Red
            else:
                color = (200, 200, 200) # Grey
                
            label = f"#{i+1} {chem.upper()} ({severity}) {reason}"
        
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
    total_water = sum(1 for r in all_results if str(r.get('water','no')).lower() == 'yes')
    total_fert = sum(1 for r in all_results if str(r.get('fertilizer','no')).lower() == 'yes')
    total_herb = sum(1 for r in all_results if str(r.get('herbicide','no')).lower() == 'yes')
    total_pest = sum(1 for r in all_results if str(r.get('pesticide','no')).lower() == 'yes')
    plants_treated = sum(1 for r in all_results if any(str(r.get(k,'no')).lower() == 'yes' for k in ['water', 'fertilizer', 'herbicide', 'pesticide']))
    
    report.append(f"\nTotal plants scanned: {total}")
    report.append(f"  💧 Water:    {total_water} needs it")
    report.append(f"  🧪 Fertilizer: {total_fert} needs it")
    report.append(f"  🌿 Herbicide: {total_herb} needs it")
    report.append(f"  🐛 Pesticide: {total_pest} needs it")
    report.append(f"\nPlants needing treatment: {plants_treated}/{total}")
    
    report.append("\n" + "=" * 40)
    report.append("DETAILED ASSESSMENT")
    report.append("=" * 40)
    
    for i, r in enumerate(all_results):
        plant_num = i + 1
        w = str(r.get('water','no')).lower()
        f = str(r.get('fertilizer','no')).lower()
        h = str(r.get('herbicide','no')).lower()
        p = str(r.get('pesticide','no')).lower()
        reason = r.get('reason', 'N/A')
        pumped = [n for n, val in [(1, w), (2, f), (3, h), (4, p)] if val == 'yes']
        
        report.append(f"\nPlant {plant_num}:")
        report.append(f"  Needs: 💧{w} 🧪{f} 🌿{h} 🐛{p}")
        report.append(f"  Reason: {reason}")
        if pumped:
            names = [PUMP_LABELS[p] for p in pumped]
            report.append(f"  Action: ✅ Sprayed {', '.join(names)}")
        else:
            report.append(f"  Action: ✅ No spray needed")
    
    report.append("\n" + "=" * 40)
    if plants_treated > 0:
        report.append(f"{plants_treated} of {total} plants received treatment.")
    else:
        report.append("All plants look healthy! 🌱")
    
    report_text = "\n".join(report)
    return report_text, {"treated": plants_treated, "total": total}


def main():
    print("=== Find Plants, Analyze, Spray, Report ===\n")
    
    # Step 1: Capture from video1 for SAM
    print("[1/7] Capturing from video1 for plant detection...")
    frame = capture_camera(VIDEO1_DEVICE)  # SAM detection from video1
    sam_input = "/tmp/v1_for_sam.jpg"
    cv2.imwrite(sam_input, frame)
    print(f"  Saved: {frame.shape[1]}x{frame.shape[0]}")
    
    # Step 2: Run SAM with "plant" prompt
    print("\n[2/7] Running SAM (plant detection)...")
    result = run_sam(sam_input, prompt="plant", confidence=CONFIDENCE)
    dets = result.get('metadata', {}).get('detections', [])
    print(f"  Detections: {len(dets)}")
    
    if not dets:
        print("ERROR: No plants found!")
        send_telegram_message("❌ No plants detected. Please check camera.")
        return
    
    # Step 3: Merge overlapping bounding boxes
    print("\n[3/7] Merging overlapping bounding boxes...")
    merged = merge_overlapping_boxes(dets)
    print(f"  Merged into {len(merged)} plant groups")
    
    for i, box in enumerate(merged):
        print(f"  Plant {i+1}: center=({box['cx']:.0f},{box['cy']:.0f}), conf={box['conf']:.3f}, count={box['count']}")
    
    # Draw merged boxes
    annotated = draw_merged_boxes(frame, merged)
    cv2.imwrite('/tmp/sam_merged_result.jpg', annotated)
    send_telegram_photo('/tmp/sam_merged_result.jpg',
        f"🌱 SAM: {len(dets)} detections → {len(merged)} plants")
    
    # Step 4: Process each plant (move, capture, analyze, spray)
    print(f"\n[4/7] Processing {len(merged)} plants...")
    all_analysis_results = []
    all_capture_paths = []
    
    for i, box in enumerate(merged):
        cx, cy = box['cx'], box['cy']
        dx, dy = calc_move(cx, cy)
        dist = math.sqrt(dx*dx + dy*dy)
        
        print(f"\n  === Plant {i+1}/{len(merged)} ===")
        print(f"  Center=({cx:.0f},{cy:.0f}) -> move x={dx}, y={dy}")
        
        # Move to plant
        print(f"  Moving to plant...")
        move_gantry(dx, dy)
        # Gantry moves ~2.3 cm/s, add settle overhead
        wait_time = int(dist / 2.3) + 8
        print(f"    Waiting ~{wait_time}s for gantry...")
        wait_for_gantry(timeout=wait_time)
        time.sleep(2)
        
        # Capture with video0
        print(f"  Capturing with video0...")
        v0_frame = capture_video0()  # capture cam (different from SAM cam)
        capture_path = f"/tmp/plant_{i+1}_capture.jpg"
        cv2.imwrite(capture_path, v0_frame)
        all_capture_paths.append(capture_path)
        print(f"  Saved: {capture_path}")
        
        # Send capture to Telegram
        send_telegram_photo(capture_path,
            f"🌿 Plant {i+1}/{len(merged)} — center=({cx:.0f},{cy:.0f}), conf={box['conf']:.3f}")
        
        # Step 5: Analyze with Ollama Gemma
        print(f"\n  [5/7] Analyzing with Ollama Gemma...")
        analysis = analyze_with_ollama(capture_path)
        all_analysis_results.append(analysis)
        
        w = str(analysis.get('water','no')).lower()
        f = str(analysis.get('fertilizer','no')).lower()
        h = str(analysis.get('herbicide','no')).lower()
        p = str(analysis.get('pesticide','no')).lower()
        reason = analysis.get('reason', '')
        
        print(f"    Result: water={w}, fertilizer={f}, herbicide={h}, pesticide={p}")
        print(f"    Reason: {reason}")
        
        # Determine which pumps to run (any "yes")
        pumps_to_fire = []
        if w == 'yes':
            pumps_to_fire.append(1)
        if f == 'yes':
            pumps_to_fire.append(2)
        if h == 'yes':
            pumps_to_fire.append(3)
        if p == 'yes':
            pumps_to_fire.append(4)
        
        # Send analysis to Telegram
        scores_msg = f"🔍 Plant {i+1}/{len(merged)}:\n  💧 water={w}  🧪 fertilizer={f}\n  🌿 herbicide={h}  🐛 pesticide={p}\n  Reason: {reason}"
        if pumps_to_fire:
            pump_names = [PUMP_LABELS[p] for p in pumps_to_fire]
            scores_msg += f"\n  💉 Spraying: {', '.join(pump_names)}"
        else:
            scores_msg += f"\n  ✅ No spray needed"
        send_telegram_message(scores_msg)
        
        # Step 6: Spray all needed pumps
        if pumps_to_fire:
            print(f"\n  [6/7] Spraying pumps: {pumps_to_fire}")
            for pump in pumps_to_fire:
                duration = SPRAY_DURATION[pump]
                print(f"    Spraying {PUMP_LABELS[pump]} (pump {pump}) for {duration}s...")
                spray_pump(pump, duration)
            send_telegram_message(f"✅ Plant {i+1} done: {', '.join([PUMP_LABELS[p] for p in pumps_to_fire])}")
        else:
            print(f"  [6/7] No spray needed")
            send_telegram_message(f"ℹ️ Plant {i+1}: No spray needed")
        
        # Return home
        print(f"\n  Returning home (move x={-dx}, y={-dy})...")
        move_gantry(-dx, -dy)
        wait_time = int(dist / 2.3) + 8
        print(f"    Waiting ~{wait_time}s for gantry...")
        wait_for_gantry(timeout=wait_time)
        time.sleep(1)
        
        print(f"  Plant {i+1} complete\n")
    
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
        chem = ar.get('chemical', 'unknown')
        caption = f"Plant {i+1}/{len(all_capture_paths)}: {chem.upper()}"
        send_telegram_photo(path, caption)
    
    # Send annotated result
    annotated_final = draw_merged_boxes(frame, merged, all_analysis_results)
    cv2.imwrite('/tmp/final_annotated_result.jpg', annotated_final)
    send_telegram_photo('/tmp/final_annotated_result.jpg',
        "🗺️ All plants with treatment decisions")
    
    # Send final report
    send_telegram_message(report_text)
    
    print("\n=== COMPLETE ===")
    print(f"Total plants: {len(merged)}")
    print(f"Report sent to Telegram.")


if __name__ == "__main__":
    main()
