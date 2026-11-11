#!/usr/bin/env python3
"""
IP Camera Capture Server using RTSP streams from Lorex cameras.
Provides ArUco detection and capture endpoints similar to USB camera server.
"""

from flask import Flask, request, jsonify
import cv2
import numpy as np
import json
import subprocess
import os
import time
from datetime import datetime

app = Flask(__name__)

# RTSP Camera configuration
CAMERAS = {
    0: {
        "name": "Camera 52",
        "rtsp": "rtsp://admin:Agribot%401234@192.168.1.52:554/",
        "enabled": False
    },
    1: {
        "name": "Camera 57",
        "rtsp": "rtsp://admin:Agribot%401234@192.168.1.57:554/",
        "enabled": False
    }
}

# USB Camera configuration (V4L2 video devices)
USBCAMERAS = {
    0: {"name": "USB Cam 0", "device": "/dev/video0", "enabled": True},
    1: {"name": "USB Cam 2", "device": "/dev/video2", "enabled": True},
    2: {"name": "USB Cam 4", "device": "/dev/video4", "enabled": True},
}

# OpenCV VideoCaptures for RTSP cameras
caps = {}

# OpenCV VideoCaptures for USB cameras
usb_caps = {}

def get_capture(cam_index):
    """Get or create video capture for RTSP camera index."""
    if cam_index not in CAMERAS or not CAMERAS[cam_index]["enabled"]:
        return None

    if cam_index not in caps or caps[cam_index] is None or not caps[cam_index].isOpened():
        if cam_index in caps and caps[cam_index] is not None:
            try:
                caps[cam_index].release()
            except:
                pass
        cap = cv2.VideoCapture(CAMERAS[cam_index]["rtsp"], cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 15000)
        caps[cam_index] = cap
    return caps[cam_index]

def get_usb_capture(usb_index):
    """Get or create video capture for USB camera index."""
    if usb_index not in USBCAMERAS or not USBCAMERAS[usb_index]["enabled"]:
        return None

    if usb_index not in usb_caps or usb_caps[usb_index] is None or not usb_caps[usb_index].isOpened():
        if usb_index in usb_caps and usb_caps[usb_index] is not None:
            try:
                usb_caps[usb_index].release()
            except:
                pass
        dev = USBCAMERAS[usb_index]["device"]
        # Try V4L2 first, fall back to FFmpeg
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(dev, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Try to set resolution to 1280x720 (wide HD)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        usb_caps[usb_index] = cap
    return usb_caps[usb_index]

def flush_buffer(cap):
    """Flush internal buffer to get fresh frame."""
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    return ret, frame

@app.route("/health", methods=["GET"])
def health_check():
    """Check service health."""
    camera_status = {}
    for idx, cam in CAMERAS.items():
        cap = get_capture(idx)
        camera_status[idx] = {
            "enabled": cam["enabled"],
            "connected": cap.isOpened() if cap else False
        }

    return jsonify({
        "status": "healthy",
        "service": "ip-capture-server",
        "cameras": camera_status,
        "timestamp": int(time.time())
    })

@app.route("/cameras", methods=["GET"])
def list_cameras():
    """List available cameras."""
    ip_available = [idx for idx, cam in CAMERAS.items() if cam["enabled"]]
    usb_available = [idx for idx, cam in USBCAMERAS.items() if cam["enabled"]]
    return jsonify({
        "ip_cameras": ip_available,
        "usb_cameras": usb_available,
        "count": len(ip_available) + len(usb_available)
    })

@app.route("/capture", methods=["POST", "GET"])
def capture_image():
    """Capture image from specified camera using ffmpeg (more reliable for RTSP)."""
    camera_index = request.args.get("camera_index", 0, type=int)
    fresh = request.args.get("fresh", "true").lower() == "true"

    if camera_index not in CAMERAS or not CAMERAS[camera_index]["enabled"]:
        return jsonify({"success": False, "error": f"Camera {camera_index} not configured"}), 404

    rtsp_url = CAMERAS[camera_index]["rtsp"]
    timestamp = int(time.time())
    save_path = f"/home/pairaiworkstation/MAATI-Bot_data/raw_capture/ip_capture_{timestamp}.jpg"
    
    # Use ffmpeg to capture - more reliable for RTSP streams
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "udp",
        "-timeout", "10000000",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-q:v", "2",
        save_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0 or not os.path.exists(save_path):
        return jsonify({
            "success": False,
            "error": f"FFmpeg capture failed: {result.stderr[-200:]}"
        }), 500

    return jsonify({
        "success": True,
        "file_path": save_path,
        "timestamp": timestamp,
        "camera_index": camera_index,
        "fresh": fresh
    })

@app.route("/usb_capture", methods=["POST", "GET"])
def usb_capture_image():
    """Capture image from USB camera (V4L2)."""
    usb_index = request.args.get("usb_index", 0, type=int)

    if usb_index not in USBCAMERAS or not USBCAMERAS[usb_index]["enabled"]:
        return jsonify({"success": False, "error": f"USB camera {usb_index} not configured"}), 404

    cap = get_usb_capture(usb_index)
    if not cap or not cap.isOpened():
        return jsonify({"success": False, "error": f"Could not open USB camera {usb_index}"}), 500

    # Flush buffer for fresh frame
    for _ in range(5):
        cap.read()
    ret, frame = cap.read()
    if not ret:
        return jsonify({"success": False, "error": "Failed to read frame from USB camera"}), 500

    timestamp = int(time.time())
    save_path = f"/home/pairaiworkstation/MAATI-Bot_data/raw_capture/usb_capture_{timestamp}.jpg"
    cv2.imwrite(save_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

    return jsonify({
        "success": True,
        "file_path": save_path,
        "timestamp": timestamp,
        "usb_index": usb_index,
        "usb_camera": USBCAMERAS[usb_index]["name"],
        "resolution": {"width": frame.shape[1], "height": frame.shape[0]}
    })

@app.route("/aruco_detect", methods=["POST", "GET"])
def aruco_detect():
    """Detect ArUco markers in camera feed."""
    camera_index = request.args.get("camera_index", 0, type=int)
    
    cam = get_capture(camera_index)
    if not cam or not cam.isOpened():
        return jsonify({
            "success": False,
            "error": f"Could not open camera {camera_index}"
        }), 500

    # Flush buffer for fresh frame
    for _ in range(10):
        cam.read()
    ret, frame = cam.read()
    if not ret:
        return jsonify({
            "success": False,
            "error": "Failed to read frame"
        }), 500

    # ArUco detection (OpenCV 4.13+ uses ArucoDetector)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    parameters = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(dictionary, parameters)
    corners, ids, rejected = detector.detectMarkers(frame)

    markers = []
    if ids is not None:
        for i, corner in enumerate(corners):
            c = corner[0]
            center_x = np.mean(c[:, 0])
            center_y = np.mean(c[:, 1])

            # Calculate bounding box
            x_min = int(np.min(c[:, 0]))
            y_min = int(np.min(c[:, 1]))
            x_max = int(np.max(c[:, 0]))
            y_max = int(np.max(c[:, 1]))

            markers.append({
                "id": int(ids[i][0]),
                "center": {"x": float(center_x), "y": float(center_y)},
                "bbox": {
                    "x": x_min, "y": y_min,
                    "x_max": x_max, "y_max": y_max,
                    "width": x_max - x_min,
                    "height": y_max - y_min
                },
                "corners": c.tolist()
            })

    timestamp = int(time.time())

    return jsonify({
        "success": True,
        "markers_detected": len(markers),
        "markers": markers,
        "rejected_candidates": len(rejected),
        "timestamp": timestamp
    })

# Fixed marker positions (pixel coordinates from calibration)
MARKER_POSITIONS = {
    7:  (1014.5, 521.0),
    8:  (3262.0, 848.25),
    9:  (3196.5, 1968.5),
    10: (798.0, 1728.75),
}

# Marker outer corner indices (0=tl, 1=tr, 2=br, 3=bl)
MARKER_OUTER_CORNER = {7: 0, 8: 1, 9: 2, 10: 3}

MARKER_SIZE = 144.0
HALF = MARKER_SIZE / 2

def get_outer_corner(marker_id, cx, cy):
    """Get outer rectangle corner from marker center."""
    corner_idx = MARKER_OUTER_CORNER[marker_id]
    d = [(-1, -1), (1, -1), (1, 1), (-1, 1)][corner_idx]
    return np.array([cx + d[0] * HALF, cy + d[1] * HALF], dtype=np.float32)

@app.route("/crop_rectangle", methods=["POST", "GET"])
def crop_rectangle():
    """
    Capture and crop rectangle using fixed marker positions.
    Uses outer corners of markers 7,8,9,10 to crop a 4ft x 2ft rectangle.
    Uses ffmpeg for fresh UDP capture, OpenCV only for warping.
    """
    camera_index = request.args.get("camera_index", 0, type=int)

    # Use ffmpeg for fresh UDP capture (no OpenCV buffer)
    rtsp_url = CAMERAS[camera_index]["rtsp"]
    timestamp = int(time.time())
    raw_path = f"/tmp/cam_raw_{timestamp}.jpg"
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "udp",
        "-timeout", "8000000",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-update", "1",
        raw_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return jsonify({
            "success": False,
            "error": f"FFmpeg capture failed: {result.stderr[-200:]}"
        }), 500

    frame = cv2.imread(raw_path)
    if frame is None:
        return jsonify({
            "success": False,
            "error": "Failed to decode frame"
        }), 500

    # Build source points from fixed marker positions
    src_pts = np.array([
        get_outer_corner(mid, *MARKER_POSITIONS[mid]) for mid in [7, 8, 9, 10]
    ], dtype=np.float32)

    # Destination: 4ft x 2ft at 100 pixels/ft = 400 x 200
    # Keep original resolution
    PIXELS_PER_FOOT = 1000
    out_w = int(4.0 * PIXELS_PER_FOOT)
    out_h = int(2.0 * PIXELS_PER_FOOT)
    dst_pts = np.array([
        [0, 0],
        [out_w - 1, 0],
        [out_w - 1, out_h - 1],
        [0, out_h - 1],
    ], dtype=np.float32)

    # Compute homography and warp
    H, _ = cv2.findHomography(src_pts, dst_pts)
    cropped = cv2.warpPerspective(frame, H, (out_w, out_h))

    timestamp = int(time.time())
    save_path = f"/home/pairaiworkstation/MAATI-Bot_data/raw_capture/ip_cam_{camera_index}_{timestamp}_rect.jpg"
    cv2.imwrite(save_path, cropped)

    return jsonify({
        "success": True,
        "file_path": save_path,
        "timestamp": timestamp,
        "camera_index": camera_index,
        "source_points": src_pts.tolist(),
        "destination_size": {"width": out_w, "height": out_h},
        "homography": H.tolist()
    })

@app.route("/howto", methods=["GET"])
def howto():
    """API documentation."""
    return jsonify({
        "title": "IP Camera Capture API",
        "description": "RTSP-based camera capture service with ArUco detection and rectangular crop",
        "endpoints": {
            "/health": "GET - Service health check",
            "/cameras": "GET - List available cameras",
            "/capture?camera_index=N": "POST/GET - Capture image from camera (saves to /home/pairaiworkstation/MAATI-Bot_data/raw_capture/)",
            "/aruco_detect?camera_index=N": "POST/GET - Detect ArUco markers",
            "/crop_rectangle?camera_index=N": "POST/GET - Capture and crop rectangle using fixed marker positions (markers 7,8,9,10). Outputs 4ft x 2ft rectangle at 1000 pixels/ft = 2000x1000px"
        },
        "marker_positions": {
            "7": {"x": 1014.5, "y": 521.0, "name": "a (top-left)"},
            "8": {"x": 3262.0, "y": 848.25, "name": "b (top-right)"},
            "9": {"x": 3196.5, "y": 1968.5, "name": "c (bottom-right)"},
            "10": {"x": 798.0, "y": 1728.75, "name": "d (bottom-left)"}
        },
        "rectangle_dimensions": {
            "width": "4 ft (ab = cd)",
            "height": "2 ft (da = cb)",
            "pixels_per_foot": 1000,
            "output_size": "2000 x 1000 pixels"
        },
        "cameras": {
            "0": "192.168.1.52 (Lorex)",
            "1": "192.168.1.57 (Lorex)"
        },
        "rtsp_urls": {
            "camera_52": "rtsp://admin:Agribot%401234@192.168.1.52:554/",
            "camera_57": "rtsp://admin:Agribot%401234@192.168.1.57:554/"
        }
    })

if __name__ == "__main__":
    print("Starting IP Camera Capture Server...")
    for idx, cam in CAMERAS.items():
        print(f"  Camera {idx}: {cam['name']}")
        print(f"    RTSP: {cam['rtsp']}")

    # Initialize captures
    for idx in CAMERAS.keys():
        cap = get_capture(idx)
        if cap and cap.isOpened():
            print(f"  Camera {idx}: Connected")
        else:
            print(f"  Camera {idx}: Not connected (will retry on first use)")

    app.run(host="0.0.0.0", port=8225, debug=False)