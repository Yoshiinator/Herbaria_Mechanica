#!/usr/bin/env python3
"""Ollama gemma3:latest VLM + MiniMax LLM pipeline for plant treatment."""

import base64, requests, json, os, re

MINIMAX_API_KEY = os.environ.get('MINIMAX_API_KEY', '')
MINIMAX_BASE_URL = os.environ.get('MINIMAX_BASE_URL', 'https://api.minimax.io/v1')
MINIMAX_MODEL = 'MiniMax-M2.1'
OLLAMA_URL = 'http://localhost:11434/api/generate'
OLLAMA_MODEL = 'gemma3:latest'
MINIMAX_LLM_ENDPOINT = f'{MINIMAX_BASE_URL}/chat/completions'

PROMPT = """You are a plant health analyst. Look at this crop image and describe for EACH distinct plant visible:
1. PLANT COUNT: one plant only, or multiple different species mixed together?
2. LEAF COLOR: vibrant dark green / pale green / yellowing / brown crispy / purple / mixed?
3. LEAF DAMAGE: any holes (small round / large irregular / shot-hole)?, brown spots?, crispy edges?, wilting?, drooping?
4. INSECTS: any beetles, worms, caterpillars visible on leaves or soil?
5. WEEDS: clearly different plant species growing among the main crop? (clover, grass, broadleaf weeds?)
6. SOIL: dry and cracked?, wet?, bare soil only?

Be specific and thorough. Report on ALL distinct plants shown."""

DECISION_PROMPT = """You are a crop treatment expert. Read this plant description and decide the treatment.

Rules (apply in order):
1. CHEWED HOLES + INSECTS/BEETLES visible → PESTICIDE (solo, nothing else)
2. 2+ DIFFERENT plant species mixed (crop + clover/grass/weeds) → HERBICIDE (solo, nothing else)
3. BROWN, CRISP, DRIED OUT, SEVERELY WILTED/DROOPING → WATER
4. YELLOWING, PALE, CHLOROTIC, PURPLE but alive/not crispy → FERTILIZER
5. HEALTHY, vibrant green, no damage → NONE

WATER + FERTILIZER can be combined — most prominent issue first.
PESTICIDE and HERBICIDE are solo only.

Plant description:
{description}

Return ONLY this JSON — no explanations, no preamble:
{"treatment": "water", "reason": "brief reason"}
OR for multiple:
{"treatment": ["water", "fertilizer"], "reason": "brief reason"}"""

SEVERITY = {"pesticide": 5, "herbicide": 4, "water": 3, "fertilizer": 2, "none": 1}


def ollama_vlm_describe(img_path_or_b64):
    """Get detailed description from Ollama gemma3:latest VLM."""
    if img_path_or_b64.startswith('/9j/') or img_path_or_b64.startswith('iVBOR'):
        img_b64 = img_path_or_b64
    else:
        with open(img_path_or_b64, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.1, "top_k": 40, "top_p": 0.9}
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
    resp.close()
    return resp.json().get('response', '').strip()


def minimax_llm_decide(description):
    """Get treatment decision from MiniMax LLM."""
    prompt = DECISION_PROMPT.replace("{description}", description)
    resp = requests.post(MINIMAX_LLM_ENDPOINT,
        headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
        json={"model": MINIMAX_MODEL,
              "messages": [
                  {"role": "system", "content": "You are a crop treatment expert. Output ONLY valid JSON, no explanations, no preambles, no thinking."},
                  {"role": "user", "content": prompt}
              ],
              "max_tokens": 2000,
              "reasoning": {"type": "none"}},
        timeout=30)
    content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
    content = re.sub(r'<[^>]+>', '', content)
    content = content.replace('```json', '').replace('```', '').strip()
    start = content.find('{')
    end = content.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return ['none'], 'no json found', content
    try:
        parsed = json.loads(content[start:end+1])
    except:
        return ['none'], 'no json found', content

    raw = parsed.get('treatment', 'none')
    treatments = [raw] if isinstance(raw, str) else raw
    valid = {"water", "fertilizer", "herbicide", "pesticide", "none"}
    treatments = [t for t in treatments if t in valid]

    has_pest = "pesticide" in treatments
    has_herb = "herbicide" in treatments
    has_water = "water" in treatments
    has_fert = "fertilizer" in treatments

    if has_pest or has_herb:
        treatments = [max(treatments, key=lambda t: SEVERITY.get(t, 0))]
    elif has_water and has_fert:
        treatments = ["water", "fertilizer"]
    elif has_water:
        treatments = ["water"]
    elif has_fert:
        treatments = ["fertilizer"]

    return treatments, parsed.get('reason', ''), content


def analyze(img_path):
    """Full pipeline: Ollama VLM describe + MiniMax LLM decide."""
    desc = ollama_vlm_describe(img_path)
    treatments, reason, raw = minimax_llm_decide(desc)
    return {'treatment': treatments, 'reason': reason, 'description': desc}


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 ollama_vlm_pipeline.py <image_path>")
        sys.exit(1)
    result = analyze(sys.argv[1])
    print(json.dumps(result, indent=2))
