#!/usr/bin/env python3
"""Ollama VLM describes → MiniMax LLM decides pipeline for plant treatment."""

import base64, requests, json, os, re

MINIMAX_API_KEY = os.environ.get('MINIMAX_API_KEY', '')
MINIMAX_BASE_URL = os.environ.get('MINIMAX_BASE_URL', 'https://api.minimax.io/v1')
MINIMAX_MODEL = 'MiniMax-M2.1'
OLLAMA_BASE_URL = 'http://localhost:11434'
OLLAMA_VLM_MODEL = 'gemma3:latest'
MINIMAX_LLM_ENDPOINT = 'https://api.minimax.io/v1/chat/completions'

PROMPT = """Describe this image in as much detail as possible. What do you see? Describe everything you observe — plants, soil, leaves, colors, damage, insects, weeds, or anything else visible. Be thorough and specific."""

DECISION_PROMPT = """You are a crop treatment expert. Read this plant description and decide the treatment.

Rules (apply in order):
1. If leaves have CHEWED HOLES, INSECTS/BEETLES visible, leaf parts eaten → PESTICIDE (solo, nothing else)
2. If there are 2 OR MORE CLEARLY DIFFERENT plant species mixed together (e.g. crop + clover, crop + grass) → HERBICIDE (solo, nothing else)
3. If plant leaves are BROWN, CRISP, DRIED OUT, or SEVERELY WILTED/DROOPING → WATER
4. If leaves are YELLOWING, PALE, CHLOROTIC, or PURPLE but still alive and not crispy → FERTILIZER
5. If plant is HEALTHY, vibrant green, no damage, no weeds → NONE

IMPORTANT: WATER and FERTILIZER can be applied together — whichever issue is MORE PROMINENT in the description should be listed first.
PESTICIDE and HERBICIDE are solo only — if either applies, return ONLY that treatment.

Plant description:
{description}

Return ONLY this JSON format:
{"treatment": "water", "reason": "brief reason"}
OR for multiple:
{"treatment": ["water", "fertilizer"], "reason": "brief reason"}"""

# Severity order for fallback
SEVERITY = {"pesticide": 5, "herbicide": 4, "water": 3, "fertilizer": 2, "none": 1}


def ollama_vlm_describe(img_path):
    """Get detailed description from Ollama VLM (gemma3:latest via /api/chat)."""
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
    # Parse JSON — strip reasoning/thinking blocks and markdown code blocks
    content = re.sub(r'<[^>]+>', '', content)  # remove <thinking>, <reasoning> tags
    content = re.sub(r'ylon\n.*?<\/.*?>', '', content, flags=re.DOTALL)  # remove reasoning blocks
    content = content.replace('```json', '').replace('```', '')
    # Try to find JSON object
    start = content.find('{')
    end = content.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return ['none'], 'no json found', content
    try:
        parsed = json.loads(content[start:end+1])
    except:
        return ['none'], 'no json found', content

    raw_treatment = parsed.get('treatment', 'none')

    # Normalize to list
    if isinstance(raw_treatment, str):
        treatments = [raw_treatment]
    elif isinstance(raw_treatment, list):
        treatments = raw_treatment
    else:
        treatments = ['none']

    # Valid treatments
    valid = {"water", "fertilizer", "herbicide", "pesticide", "none"}
    treatments = [t for t in treatments if t in valid]

    # Apply combination rules:
    # - PESTICIDE or HERBICIDE → solo only, most prominent wins
    # - WATER + FERTILIZER → both, whichever is MORE PROMINENT goes first
    has_pest = "pesticide" in treatments
    has_herb = "herbicide" in treatments
    has_water = "water" in treatments
    has_fert = "fertilizer" in treatments

    if has_pest or has_herb:
        # Take most prominent solo
        best = max(treatments, key=lambda t: SEVERITY.get(t, 0))
        treatments = [best]
    elif has_water and has_fert:
        # Both needed — prompt says more prominent goes first
        treatments = ["water", "fertilizer"]
    elif has_water:
        treatments = ["water"]
    elif has_fert:
        treatments = ["fertilizer"]

    final_treatment = treatments[0] if treatments else "none"
    return treatments, parsed.get('reason', ''), content


def analyze(img_path):
    """Full pipeline: Ollama VLM describe + MiniMax LLM decide. Returns dict."""
    desc = ollama_vlm_describe(img_path)
    treatments, reason, raw = minimax_llm_decide(desc)
    return {'treatment': treatments, 'reason': reason, 'description': desc}


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 ollama_v2_describe_ollamavlm.py <image_path>")
        sys.exit(1)
    result = analyze(sys.argv[1])
    print(json.dumps(result, indent=2))
