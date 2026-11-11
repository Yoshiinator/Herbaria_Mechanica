#!/usr/bin/env python3
"""Find all plants and move to each from closest to farthest."""

import os
import sys
import json
import time
import math
import requests
import io

# Config - all services on workstation
GANTRY_API = "http://192.168.1.2:8000"
CAMERA_API = "http://localhost:8225"
SAM3_API = "http://localhost:8222"

# Local paths
IMAGE_DIR = "/home/pairaiworkstation/MAATI-Bot_data/plant_captures"
RAW_CAPTURE_DIR = "/home/pairaiworkstation/MAATI-Bot_data/raw_capture"

USB_CAMERA = "/dev/video4"

# Delays (seconds)
DELAY_AFTER_MOVE = 5
DELAY_CAPTURE = 1
DELAY_BETWEEN_PLANTS = 3

HOME_PIXEL_X = 1159
HOME_PIXEL_Y = 242
PX_PER_CM_X = 14.6
PX_PER_CM_Y = 14.6

def rjson(r):
    return r.json()

def get_position():
    r = requests.get(f"{GANTRY_API}/api/gantry")
    return rjson(r)

def move_to(x_cm, y_cm, z_cm=None):
    data = {"x": x_cm, "y": y_cm}
    if z_cm is not None:
        data["z"] = z_cm
    r = requests.post(f"{GANTRY_API}/api/move_abs", json=data)
    result = rjson(r)
    print(f"  -> {result}")
    return result.get("ok", False)

def home_z():
    r = requests.post(f"{GANTRY_API}/api/home_z")
    return rjson(r)

def pixel_to_cm(px_x, px_y):
    cm_x = (HOME_PIXEL_X - px_x) / PX_PER_CM_X
    cm_y = (HOME_PIXEL_Y - px_y) / PX_PER_CM_Y
    return cm_x, cm_y

def capture_and_segment():
    """Capture image and find plants with SAM3."""
    print("[1] Capturing frame...")
    r = requests.post(f"{CAMERA_API}/capture?camera_index=0")
    result = rjson(r)
    if not result.get("success"):
        raise Exception(f"Capture failed: {result}")
    
    print("[2] Running SAM3 segmentation...")
    img_path = result.get("file_path")
    if not img_path:
        raise Exception(f"No image path: {result}")
    
    # Send image directly to SAM3
    with open(img_path, "rb") as f:
        img_data = f.read()
    
    files = {
        "file": ("image.jpg", io.BytesIO(img_data), "image/jpeg"),
        "text_prompt": (None, "plant")
    }
    
    r = requests.post(f"{SAM3_API}/api/segment", files=files, timeout=120)
    seg_result = rjson(r)
    
    if not seg_result.get("success"):
        raise Exception(f"Segmentation failed: {seg_result}")
    
    # Parse detections from metadata.detections
    meta = seg_result.get("metadata", {})
    dets = meta.get("detections", [])
    if dets:
        masks = []
        for d in dets:
            box = d.get("bounding_box", {})
            masks.append({
                "point_coords": [[(box.get("x_min",0)+box.get("x_max",0))/2, (box.get("y_min",0)+box.get("y_max",0))/2]],
                "confidence": d.get("confidence", 0)
            })
        return masks
    return []

def distance(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

def main():
    print("=== Plant Mover: Closest to Furthest ===")
    
    # Reset gantry
    print("[*] Resetting gantry...")
    home_z()
    r = requests.post(f"{GANTRY_API}/api/reset")
    print(f"  -> {rjson(r)}")
    
    # Find plants
    masks = capture_and_segment()
    
    if not masks:
        print("No plants detected!")
        return
    
    print(f"[*] Found {len(masks)} plants")
    
    # Sort by distance from home
    plants = [(m["point_coords"][0][0], m["point_coords"][0][1], m["confidence"]) for m in masks]
    plants.sort(key=lambda p: distance(p[:2], [HOME_PIXEL_X, HOME_PIXEL_Y]))
    
    # Move to each plant
    for i, (px, py, conf) in enumerate(plants):
        cm_x, cm_y = pixel_to_cm(px, py)
        print(f"[{i+1}] Moving to ({px:.0f}, {py:.0f}) -> ({cm_x:.2f}, {cm_y:.2f}) conf={conf:.2f}")
        
        # Home Z first
        home_z()
        time.sleep(DELAY_AFTER_MOVE)
        
        # Move to plant
        move_to(cm_x, cm_y)
        time.sleep(DELAY_AFTER_MOVE)
        
        print(f"  -> Arrived at plant {i+1}")

if __name__ == "__main__":
    main()