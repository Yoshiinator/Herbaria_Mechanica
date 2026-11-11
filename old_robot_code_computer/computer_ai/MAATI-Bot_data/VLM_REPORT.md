# MAATI Farm Bot — VLM Spray Report

## Project Overview

**Goal:** Automated crop analysis + robotic precision spraying using Canon top-view camera, SAM segmentation, Ollama VLM classification, and MATI gantry robot.

**Hardware Stack:**
- Canon EOS R50 — top-view farm camera
- SAM3 server — plant segmentation (localhost:8222)
- Ollama gemma3 — plant health VLM (localhost:11434)
- MATI Gantry — 3-axis farm robot (192.168.1.2:8000)
- UniFi switch (192.168.1.58)

---

## Architecture

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────┐
│  Canon EOS R50  │──────│  SAM3 Server │──────│  Ollama     │
│  (top-view)     │      │  (segment)   │      │  gemma3     │
└─────────────────┘      └──────────────┘      └─────────────┘
         │                        │                     │
         ▼                        ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    canon_topview_spray.py                        │
│  1. Capture frame                                                │
│  2. SAM detection → NMS merge boxes                              │
│  3. Spatial sort (top→bottom, left→right)                      │
│  4. Crop each plant                                             │
│  5. VLM classify (per-plant)                                    │
│  6. Annotate image                                              │
│  ────────────────────────────────────────────────────────────── │
│  7. Telegram confirm ('go')                                     │
│  8. Gantry move + pump spray (per plant)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  MATI Gantry     │
                    │  Pump 1=Water   │
                    │  Pump 2=Fert    │
                    │  Pump 3=Herbic  │
                    │  Pump 4=Pesticide│
                    └──────────────────┘
```

---

## Treatment Classification Rules

| Symptom | Treatment | Pump |
|---------|-----------|------|
| Dead/pale/crispy/brown leaves | WATER | 1 |
| Yellowing with some green | FERTILIZER | 2 |
| Multiple plant types / different leaf shapes | HERBICIDE | 3 |
| Insects, beetles, chewed holes | PESTICIDE | 4 |
| Healthy, vibrant green | none | — |

---

## VLM Prompt Evolution

### v1 — Initial (all water, no differentiation)
```
"Is this plant crop HEALTHY or WATER? Consider leaf color..."
```
**Result:** Everything → WATER

### v2 — Added categories
```
"DEAD or PALE → WATER / YELLOWING → FERTILIZER / WEEDS → HERBICIDE / INSECTS → PESTICIDE"
```
**Result:** Still everything → WATER. Model ignored rules.

### v3 — Stricter, explicit rules
```
"WATER STRESS: dead/brown/grey crispy → WATER / YELLOWING → FERTILIZER / mixed species → HERBICIDE / bugs → PESTICIDE"
```
**Result:** Better but still defaulting to WATER.

### v4 — Soil distraction fix
```
"Look at CROP PLANT ONLY, not soil. Dry cracked soil = IGNORE."
```
**Result:** Plants 1 & 4 correctly got FERTILIZER instead of WATER. Soil no longer fooling model.

### v5 — Strict precedence rules
```
"Wilting + yellow = FERTILIZER / Pale + drooping = WATER / Any insects = PESTICIDE / Mixed leaf types = HERBICIDE"
```
**Result:** Differentiated results emerging.

### v6 — Descriptive-first (current)
```
"What do you see? Describe: 1) one plant or multiple plants? 2) leaf colors and condition?
 3) any insects or holes? 4) wilting or drooping?
 Then pick ONE classification:
 - pesticide: if you see beetles, insects, or holes in leaves
 - herbicide: if you see 2 completely separate plants (one left, one right, or different spots in soil)
 - water: if leaves are brown, crispy, wilting, or drooping
 - fertilizer: if leaves are yellow or pale but still green and alive
 - none: if plant is vibrant green and healthy"
```
**Result:** Best results so far. Descriptive preamble helps model observe before classifying.

---

## Key Bugs Found & Fixed

### Bug 1: SAM3 coordinate format change (June 25)
- **Symptom:** All bounding boxes returned (0,0,0,0)
- **Root cause:** SAM3 API changed — detections moved from `result['detections']` to `result['metadata']['detections']`
- **Fix:** Updated detection extraction to check both paths

### Bug 2: Mixed coordinate system
- **Symptom:** SAM3 returning x_min/y_min normalized (0-1) but y_max/x_max in pixels
- **Root cause:** SAM3 uses mixed coordinate reporting
- **Fix:**
  ```python
  if x_min < 1.0 and y_min > 1.5:
      # Mixed mode: x_min normalized, others in pixels
      x_min_px = int(x_min * img_w)
  ```

### Bug 3: Containment merge collapsing all boxes
- **Symptom:** 78 detections → 1 merged box (all plants collapsed)
- **Root cause:** Containment rule (any corner inside another) was too aggressive on crowded farm images
- **Fix:** Switched to NMS (Non-Maximum Suppression) with IoU threshold 0.3

### Bug 4: VLM JSON array response
- **Symptom:** Model returning `[{...}, {...}]` instead of single `{...}`
- **Fix:** Parser now handles arrays — takes first element

### Bug 5: gantry moving before Phase 1 complete
- **Symptom:** User reported arm moving during analysis
- **Root cause:** Confirmed — code actually runs Phase 1 fully before Phase 2. No bug found, user verified workflow.
- **Safeguard added:** Telegram `input()` confirmation before every gantry move with flock lock

---

## Benchmark Results

### Benchmark 1 — 4 Reference Images (50 runs each)

| Image | Ground Truth | Prediction | Accuracy | Consistent? |
|-------|------------|-----------|---------|-------------|
| Img1 (wilted plant) | WATER | WATER | **94%** | ✓ |
| Img2 (yellowing) | FERTILIZER | FERTILIZER | **98%** | ✓ |
| Img3 (brassica+thistle) | HERBICIDE | WATER | **0%** | ✗ |
| Img4 (flea beetles) | PESTICIDE | PESTICIDE | **100%** | ✓ |

**Overall: 73%** (146/200)

### Benchmark 2 — 4 Field Images (50 runs each)

| Image | Ground Truth | Prediction | Accuracy | Consistent? |
|-------|------------|-----------|---------|-------------|
| Img1 (soybean yellowing) | FERTILIZER | FERTILIZER | **96%** | ✓ |
| Img2 (dry cracked soil) | WATER | WATER | **98%** | ✓ |
| Img3 (soybean+weeds) | HERBICIDE | none | **0%** | ✗ |
| Img4 (Japanese beetles) | PESTICIDE | PESTICIDE | **88%** | ✓ |

**Overall: 70.5%** (141/200)

### Combined Benchmarks — 8 images, 400 total runs

| Treatment | Images | Avg Accuracy |
|-----------|--------|-------------|
| WATER | 2 | **96%** |
| FERTILIZER | 2 | **97%** |
| PESTICIDE | 2 | **94%** |
| HERBICIDE | 2 | **0%** |
| **TOTAL** | 8 | **71.75%** |

---

## Known Issues

### Critical: HERBICIDE = 0% accuracy
- **Symptom:** Model never classifies as HERBICIDE across both benchmarks (0/100 runs)
- **Root cause:** Model describes multiple plants in its reasoning but then picks another category (water/none)
- **Affected images:** Brassica+thistle, soybean+weeds (pigweed/foxtail)
- **Status:** OPEN — prompt engineering not solving this. May need:
  - Different model (gemma3 may be weak on plant species differentiation)
  - Crop-level SAM segmentation to isolate individual plants before VLM
  - Explicit few-shot examples in prompt

### FERTILIZER borderline
- Some "pale but healthy" plants get "none" instead of FERTILIZER
- Accuracy 97% but one image (Img1 benchmark 1) only 80% accurate in 5-run test
- Lower priority — model mostly gets this right

### SAM segmentation quality
- On crowded/dense images, SAM produces many small overlapping boxes
- NMS helps but crops can still be too small or misaligned
- Lower priority for now since we can run VLM on full images

---

## Files

| File | Purpose |
|------|---------|
| `canon_topview_spray.py` | Main script — capture + SAM + VLM + gantry spray |
| `VLM_REPORT.md` | This report |
| `vlm_benchmark_results.json` | Benchmark 1 raw results (4 images × 50 runs) |
| `vlm_benchmark_results.csv` | Benchmark 1 CSV export |
| `vlm_benchmark2_results.json` | Benchmark 2 raw results (4 images × 50 runs) |
| `vlm_benchmark2_results.csv` | Benchmark 2 CSV export |
| `benchmark2_images.json` | Image file references for benchmark 2 |

---

## Commands

```bash
# Run full analysis + spray
cd /home/pairaiworkstation/MAATI-Bot_data
uv run --with opencv-python-headless python canon_topview_spray.py

# SAM3 server
curl http://localhost:8222/docs

# Ollama models
curl http://localhost:11434/api/tags
```
