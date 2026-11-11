#!/usr/bin/env python3
"""
IP Camera Capture Server using RTSP streams from Lorex cameras.
Provides ArUco detection and capture endpoints similar to USB camera server.
"""

from flask import Flask, request, jsonify
import cv2
import numpy as np
import json
import time
import os
from datetime import datetime

app = Flask(__name__)

# RTSP Camera configuration
CAMERAS = {
    0: {
        "name": "Camera 52",
        "rtsp": "rtsp://admin:Agribot%401234@192.168.1.52:554/",
        "enabled": True
    },
    1: {
        "name": "Camera 57",
        "rtsp": "rtsp://admin:Agribot%401234@192.168.1.57:554/",
        "enabled": True
    }
}

# OpenCV VideoCaptures for each camera
caps = {}

# Camera calibration data (loaded from files)
calibration = {}

def load_calibration(cam_index):
    """Load calibration for camera."""
    calib_file = f"/home/pairaiworkstation/MAATI-Bot_data/ip_calibration/camera_{cam_index}_calibration.json"
    if os.path.exists(calib_file):
        with open(calib_file, 'r') as f:
            data = json.load(f)
            calibration[cam_index] = {
                "camera_matrix": np.array(data["camera_matrix"], dtype=np.float64),
                "distortion_coefficients": np.array(data["distortion_coefficients"], dtype=np.float64),
                "image_size": tuple(data["image_size"])
            }
            return True
    return False

# Load calibration for both cameras
load_calibration(0)
load_calibration(1)

def undistort_frame(frame, cam_index):
    """Undistort frame using calibration data."""
    if cam_index not in calibration:
        return frame
    calib = calibration[cam_index]
    h, w = frame.shape[:2]
    new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
        calib["camera_matrix"], calib["distortion_coefficients"], (w, h), 1, (w, h)
    )
    undistorted = cv2.undistort(frame, calib["camera_matrix"], calib["distortion_coefficients"], None, new_camera_matrix)
    return undistorted

def get_capture(cam_index):
    """Get or create video capture for camera index."""
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
        caps[cam_index] = cap
    return caps[cam_index]

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
    available = [idx for idx, cam in CAMERAS.items() if cam["enabled"]]
    return jsonify({
        "available_cameras": available,
        "count": len(available)
    })

@app.route("/capture", methods=["POST", "GET"])
def capture_image():
    """Capture image from specified camera."""
    camera_index = request.args.get("camera_index", 0, type=int)

    cap = get_capture(camera_index)
    if not cap or not cap.isOpened():
        return jsonify({
            "success": False,
            "error": f"Could not open camera {camera_index}"
        }), 500

    ret, frame = cap.read()
    if not ret:
        return jsonify({
            "success": False,
            "error": f"Failed to read frame from camera {camera_index}"
        }), 500

    # Apply undistortion if calibration available
    frame = undistort_frame(frame, camera_index)

    timestamp = int(time.time())
    save_path = f"/home/pairaiworkstation/MAATI-Bot_data/raw_capture/ip_capture_{timestamp}.jpg"
    cv2.imwrite(save_path, frame)

    return jsonify({
        "success": True,
        "file_path": save_path,
        "timestamp": timestamp,
        "camera_index": camera_index,
        "frame_shape": frame.shape
    })

@app.route("/aruco_detect", methods=["POST", "GET"])
def aruco_detect():
    """Detect ArUco markers in camera feed."""
    camera_index = request.args.get("camera_index", 0, type=int)
    cap = get_capture(camera_index)

    if not cap or not cap.isOpened():
        return jsonify({
            "success": False,
            "error": f"Could not open camera {camera_index}"
        }), 500

    ret, frame = cap.read()
    if not ret:
        return jsonify({
            "success": False,
            "error": "Failed to read frame"
        }), 500

    try:
        # Create fresh capture for aruco to avoid segfault
        aruco_cap = cv2.VideoCapture(CAMERAS[camera_index]["rtsp"], cv2.CAP_FFMPEG)
        aruco_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret2, frame2 = aruco_cap.read()
        aruco_cap.release()

        if not ret2:
            return jsonify({
                "success": False,
                "error": "Failed to read frame for ArUco"
            }), 500

        # Apply undistortion if calibration available
        frame2 = undistort_frame(frame2, camera_index)

        # Resize for ArUco to avoid segfault on high-res images
        small_frame = cv2.resize(frame2, (frame2.shape[1]//4, frame2.shape[0]//4))
        scale = 4

        # ArUco detection
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        parameters = cv2.aruco.DetectorParameters_create()
        corners, ids, rejected = cv2.aruco.detectMarkers(small_frame, aruco_dict, parameters=parameters)

        markers = []
        if ids is not None:
            for i, corner in enumerate(corners):
                c = corner[0]
                # Scale back to original resolution
                center_x = np.mean(c[:, 0]) * scale
                center_y = np.mean(c[:, 1]) * scale

                # Calculate bounding box (scaled back to original resolution)
                x_min = int(np.min(c[:, 0]) * scale)
                y_min = int(np.min(c[:, 1]) * scale)
                x_max = int(np.max(c[:, 0]) * scale)
                y_max = int(np.max(c[:, 1]) * scale)

                markers.append({
                    "id": int(ids[i][0]),
                    "center": {"x": float(center_x), "y": float(center_y)},
                    "bbox": {
                        "x": x_min, "y": y_min,
                        "x_max": x_max, "y_max": y_max,
                        "width": x_max - x_min,
                        "height": y_max - y_min
                    },
                    "corners": (c * scale).tolist()
                })

        timestamp = int(time.time())

        return jsonify({
            "success": True,
            "markers_detected": len(markers),
            "markers": markers,
            "rejected_candidates": len(rejected),
            "timestamp": timestamp
        })
    except Exception as e:
        # On error, force recreate capture
        if camera_index in caps:
            try:
                caps[camera_index].release()
            except:
                pass
            caps[camera_index] = None
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

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
    Uses fresh VideoCapture to avoid buffered frames.
    """
    camera_index = request.args.get("camera_index", 0, type=int)

    # Create fresh VideoCapture to avoid buffered frames
    rtsp = CAMERAS[camera_index]["rtsp"]
    fresh_cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
    fresh_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Flush buffer by reading a few frames
    for _ in range(3):
        fresh_cap.read()
        time.sleep(0.1)

    ret, frame = fresh_cap.read()
    fresh_cap.release()

    if not ret:
        return jsonify({
            "success": False,
            "error": "Failed to read frame"
        }), 500

    # Apply undistortion if calibration available
    frame = undistort_frame(frame, camera_index)

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

    app.run(host="0.0.0.0", port=8224, debug=False)
