#!/usr/bin/env python3
"""Benchmark Ollama VLM (gemma3:latest) + MiniMax LLM on individual plant crops.

Each plant crop is described + decided separately.
Ground truth from batch_run_results.json (MiniMax VL pipeline).
Saves: benchmark_ollama_results.json + benchmark_ollama_results.csv
"""

import sys, os, json, base64, time, csv, cv2
sys.path.insert(0, '.')
from canon_topview_spray import run_sam, nms_detections
from ollama_v2_describe_ollamavlm import minimax_llm_decide
import requests

OLLAMA_BASE_URL = 'http://localhost:11434'
OLLAMA_VLM_MODEL = 'gemma3:latest'

PROMPT = """Describe this image in as much detail as possible. What do you see? Describe everything you observe — plants, soil, leaves, colors, damage, insects, weeds, or anything else visible. Be thorough and specific."""

def ollama_vlm_describe(img_path):
    with open(img_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": OLLAMA_VLM_MODEL,
        "messages": [{"role": "user", "content": PROMPT, "images": [img_b64]}],
        "stream": False
    }
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120)
    resp.close()
    result = resp.json()
    if 'error' in result:
        raise Exception(f"Ollama error: {result['error']}")
    return result.get('message', {}).get('content', '').strip()

# Load ground truth
with open('/home/pairaiworkstation/MAATI-Bot_data/batch_run_results.json') as f:
    gt_data = json.load(f)

IMAGES = [
    "/home/pairaiworkstation/.hermes/image_cache/img_2071869f9dab.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_aecb81397a1e.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_08cbec150698.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_8d19c7d050a2.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_32fecf92b906.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_611ac2bca3a0.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_e6af07aa7945.jpg",
    "/home/pairaiworkstation/.hermes/image_cache/img_91e73a12ac22.jpg",
]

RUNS = 5
all_results = []
csv_rows = []

for run in range(RUNS):
    print(f"\n=== Run {run+1}/{RUNS} ===")
    for img_path in IMAGES:
        name = os.path.basename(img_path)
        img = cv2.imread(img_path)
        if img is None:
            print(f"  SKIP {name}: not found")
            continue

        img_gt = gt_data.get(name, {})
        num_plants = img_gt.get('plants', 0)

        # Get SAM detections for this image
        dets = run_sam(img_path, "plant")
        nms = nms_detections(dets['detections'], iou_threshold=0.4)

        print(f"  {name}: {len(nms)} plants detected, {num_plants} in ground truth")

        # Process each detected plant as a crop
        gt_entry = img_gt.get('results', {})

        for i, d in enumerate(nms):
            x1, y1, x2, y2 = d['x_min'], d['y_min'], d['x_max'], d['y_max']
            crop = img[y1:y2, x1:x2]
            crop_path = f"/tmp/bench_crop_{run}_{name}_p{i+1}.jpg"
            ok = cv2.imwrite(crop_path, crop)
            if not ok:
                continue

            try:
                start = time.time()
                desc = ollama_vlm_describe(crop_path)
                elapsed = time.time() - start
                treatments, reason, raw = minimax_llm_decide(desc)
            except Exception as e:
                print(f"    #{i+1}: ERROR {e}")
                desc = ""
                treatments = ["error"]
                reason = str(e)
                elapsed = 0

            # Get ground truth for this plant number (match by position)
            plant_num = str(i + 1)
            expected = gt_entry.get(plant_num, {}).get('treatment', ['unknown'])
            if isinstance(expected, str):
                expected = [expected]

            predicted = treatments if isinstance(treatments, list) else [treatments]
            exact = predicted[0] in expected if predicted and expected else False
            partial = any(p in expected for p in predicted) if predicted else False

            print(f"    #{i+1}: predicted={predicted}, expected={expected}, exact={exact}")

            row = {
                "run": run + 1,
                "image": name,
                "plant": i + 1,
                "predicted": predicted,
                "expected": expected,
                "exact_match": exact,
                "partial_match": partial,
                "vl_time_s": round(elapsed, 1),
                "description": desc[:300] if desc else "",
                "reason": reason[:200] if reason else "",
            }
            csv_rows.append(row)
            all_results.append(row)

    # Running accuracy
    exact_total = sum(1 for r in all_results if r['exact_match'])
    partial_total = sum(1 for r in all_results if r['partial_match'])
    total = len(all_results)
    print(f"\n--- After run {run+1}: exact={exact_total}/{total} ({100*exact_total/total:.1f}%), partial={partial_total}/{total} ({100*partial_total/total:.1f}%) ---")

# Save
out_json = '/home/pairaiworkstation/MAATI-Bot_data/benchmark_ollama_results.json'
with open(out_json, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nSaved JSON: {out_json} ({len(all_results)} entries)")

out_csv = '/home/pairaiworkstation/MAATI-Bot_data/benchmark_ollama_results.csv'
if csv_rows:
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_rows[0].keys())
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"Saved CSV: {out_csv}")

# Summary
exact = sum(1 for r in all_results if r['exact_match'])
partial = sum(1 for r in all_results if r['partial_match'])
total = len(all_results)
avg_time = sum(r['vl_time_s'] for r in all_results) / total if total else 0

print(f"\n{'='*55}")
print(f"BENCHMARK RESULTS: gemma3:latest + MiniMax LLM")
print(f"VLM prompt: generic open-ended description")
print(f"{'='*55}")
print(f"Runs: {RUNS}, Images: {len(IMAGES)}, Total plant-crops: {total}")
print(f"Exact match: {exact}/{total} = {100*exact/total:.1f}%")
print(f"Partial match: {partial}/{total} = {100*partial/total:.1f}%")
print(f"Avg VL time: {avg_time:.1f}s/crop")
print(f"\nPer-treatment accuracy:")
from collections import Counter
for treatment in ['herbicide', 'pesticide', 'water', 'fertilizer', 'none']:
    pred_count = sum(1 for r in all_results if r['predicted'][0] == treatment)
    exp_count = sum(1 for r in all_results if r['expected'][0] == treatment)
    correct = sum(1 for r in all_results if r['exact_match'] and r['predicted'][0] == treatment)
    print(f"  {treatment:12}: predicted={pred_count}, expected={exp_count}, correct={correct}")

print(f"\nPer-image breakdown:")
for img in sorted(set(r['image'] for r in all_results)):
    img_rows = [r for r in all_results if r['image'] == img]
    total_img = len(img_rows)
    exact_img = sum(1 for r in img_rows if r['exact_match'])
    print(f"  {img}: {exact_img}/{total_img} exact ({100*exact_img/total_img:.0f}%)")
