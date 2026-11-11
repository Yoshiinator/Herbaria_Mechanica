"""
SSH Camera Capture Service
Run on 192.168.1.2 to capture images from camera and save to network drive.

Folder Structure:
  //192.168.1.2/SharedFiles/
    ├── raw_capture/        - Original captured images
    ├── segments/           - Segmentation results from SAM3
    ├── metadata/           - JSON metadata files
    ├── calibration/        - Camera calibration images and params
    └── cache/              - Temporary files

Endpoints:
  GET  /health             - Health check
  POST /capture             - Capture image (saves to raw_capture, returns path)
  POST /capture_base64      - Capture + return base64 (saves to raw_capture)
  POST /calibration_capture - Capture calibration chessboard image
  POST /calibration_compute  - Compute calibration from captured images
  GET  /calibration_info    - Get current calibration parameters
  GET  /list                - List all folders
  GET  /list/raw_capture    - List raw captures
  GET  /list/segments       - List segmentation results
  GET  /list/metadata       - List metadata files
  GET  /list/calibration    - List calibration images
"""

import base64
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request


# Configuration
NETWORK_PATH = "//192.168.1.2/SharedFiles"
RAW_CAPTURE_FOLDER = "raw_capture"
SEGMENTS_FOLDER = "segments"
METADATA_FOLDER = "metadata"
CALIBRATION_FOLDER = "calibration"
CACHE_FOLDER = "cache"
CALIBRATION_BOARD = (9, 6)  # Inner corners (cols, rows)
SQUARE_SIZE = 0.025  # 25mm in meters
CALIBRATION_OUTPUT_FILE = "//192.168.1.2/SharedFiles/calibration/camera_calibration.json"
CAPTURE_DEVICE = 0


app = Flask(__name__)


def ensure_folder(folder_name):
    """Ensure folder exists on network drive."""
    folder_path = Path(NETWORK_PATH) / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def get_timestamp_path(folder_name, extension="jpg"):
    """Generate timestamped filename and return full path."""
    timestamp = int(time.time())
    filename = f"{timestamp}.{extension}"
    return timestamp, str(Path(NETWORK_PATH) / folder_name / filename)


@app.route("/health")
def health_check():
    """Health check endpoint."""
    ensure_folder(CALIBRATION_FOLDER)
    return jsonify({
        "status": "healthy",
        "network_path": NETWORK_PATH,
        "folders": {
            "raw_capture": str(Path(NETWORK_PATH) / RAW_CAPTURE_FOLDER),
            "segments": str(Path(NETWORK_PATH) / SEGMENTS_FOLDER),
            "metadata": str(Path(NETWORK_PATH) / METADATA_FOLDER),
            "calibration": str(Path(NETWORK_PATH) / CALIBRATION_FOLDER),
            "cache": str(Path(NETWORK_PATH) / CACHE_FOLDER),
        },
        "capture_device": CAPTURE_DEVICE,
    })


@app.route("/capture", methods=["POST", "GET"])
def capture_image():
    """Capture image and save to raw_capture folder."""
    camera_index = request.args.get("camera_index", CAPTURE_DEVICE, type=int)

    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return jsonify({"success": False, "error": f"Could not open camera {camera_index}"}), 500

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return jsonify({"success": False, "error": "Failed to capture frame"}), 500

        timestamp, save_path = get_timestamp_path(RAW_CAPTURE_FOLDER)
        cv2.imwrite(save_path, frame)

        windows_path = save_path.replace("/", "\\")

        return jsonify({
            "success": True,
            "file_path": save_path,
            "file_path_windows": windows_path,
            "timestamp": timestamp,
            "message": "Image captured and saved to raw_capture"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/capture_base64", methods=["POST", "GET"])
def capture_base64():
    """Capture image, save to raw_capture, and return base64 encoded image."""
    camera_index = request.args.get("camera_index", CAPTURE_DEVICE, type=int)

    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return jsonify({"success": False, "error": f"Could not open camera {camera_index}"}), 500

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return jsonify({"success": False, "error": "Failed to capture frame"}), 500

        timestamp, save_path = get_timestamp_path(RAW_CAPTURE_FOLDER)
        cv2.imwrite(save_path, frame)

        with open(save_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')

        windows_path = save_path.replace("/", "\\")

        return jsonify({
            "success": True,
            "file_path": save_path,
            "file_path_windows": windows_path,
            "image_base64": img_b64,
            "timestamp": timestamp,
            "message": "Image captured, saved to raw_capture, and encoded"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/calibration_capture", methods=["POST", "GET"])
def calibration_capture():
    """
    Capture a calibration chessboard image.
    Detects and saves only if chessboard is found.
    """
    camera_index = request.args.get("camera_index", CAPTURE_DEVICE, type=int)

    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return jsonify({"success": False, "error": f"Could not open camera {camera_index}"}), 500

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return jsonify({"success": False, "error": "Failed to capture frame"}), 500

        # Check for chessboard
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, CALIBRATION_BOARD, None)

        if not found:
            return jsonify({
                "success": False,
                "error": "No chessboard detected. Ensure chessboard is visible in frame."
            }), 400

        # Save calibration image
        ensure_folder(CALIBRATION_FOLDER)
        timestamp, save_path = get_timestamp_path(CALIBRATION_FOLDER)
        cv2.imwrite(save_path, frame)

        # Refine corners
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

        # Draw for visualization
        cv2.drawChessboardCorners(frame, CALIBRATION_BOARD, corners_refined, found)

        windows_path = save_path.replace("/", "\\")

        return jsonify({
            "success": True,
            "file_path": save_path,
            "file_path_windows": windows_path,
            "timestamp": timestamp,
            "corners_detected": True,
            "message": "Calibration image captured successfully"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/calibration_compute", methods=["POST"])
def calibration_compute():
    """
    Compute camera calibration from captured chessboard images.
    Returns camera matrix, distortion coefficients, and reprojection error.
    """
    try:
        folder = Path(NETWORK_PATH) / CALIBRATION_FOLDER
        if not folder.exists():
            return jsonify({"success": False, "error": "No calibration folder"}), 400

        images = sorted(folder.glob("*.jpg"))
        if len(images) < 5:
            return jsonify({
                "success": False,
                "error": f"Need at least 5 images, found {len(images)}"
            }), 400

        # Prepare object points
        objp = np.zeros((CALIBRATION_BOARD[0] * CALIBRATION_BOARD[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:CALIBRATION_BOARD[0], 0:CALIBRATION_BOARD[1]].T.reshape(-1, 2)
        objp *= SQUARE_SIZE

        objpoints = []
        imgpoints = []
        img_size = None
        successful = 0

        for img_path in images:
            img = cv2.imread(str(img_path))
            if img is None:
                continue

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img_size = gray.shape[::-1]

            found, corners = cv2.findChessboardCorners(gray, CALIBRATION_BOARD, None)

            if found:
                objpoints.append(objp)
                imgpoints.append(corners)
                successful += 1

        if successful < 5:
            return jsonify({
                "success": False,
                "error": f"Only {successful} valid images with chessboard detected"
            }), 400

        # Calibrate
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
            objpoints, imgpoints, img_size, None, None
        )

        # Compute reprojection error
        total_error = 0
        for i in range(len(objpoints)):
            imgpoints2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], mtx, dist)
            error = cv2.norm(imgpoints[i], imgpoints2, cv2.NORM_L2) / len(imgpoints2)
            total_error += error
        mean_error = total_error / len(objpoints)

        # Save calibration
        calibration_data = {
            "camera_matrix": mtx.tolist(),
            "distortion_coefficients": dist.tolist(),
            "image_size": img_size,
            "calibration_images_used": successful,
            "mean_reprojection_error": float(mean_error),
            "square_size_meters": SQUARE_SIZE,
            "board_size": list(CALIBRATION_BOARD),
            "rvecs": [r.tolist() for r in rvecs],
            "tvecs": [t.tolist() for t in tvecs]
        }

        with open(CALIBRATION_OUTPUT_FILE, 'w') as f:
            json.dump(calibration_data, f, indent=2)

        return jsonify({
            "success": True,
            "message": f"Calibration computed from {successful} images",
            "calibration": {
                "images_used": successful,
                "mean_reprojection_error": float(mean_error),
                "image_size": img_size,
                "camera_matrix": mtx.tolist(),
                "distortion_coefficients": dist.flatten().tolist()
            },
            "calibration_saved_to": CALIBRATION_OUTPUT_FILE
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/calibration_info", methods=["GET"])
def calibration_info():
    """Get current calibration parameters."""
    if os.path.exists(CALIBRATION_OUTPUT_FILE):
        with open(CALIBRATION_OUTPUT_FILE, 'r') as f:
            calib = json.load(f)
        return jsonify({"success": True, "calibration": calib})
    return jsonify({"success": False, "error": "No calibration found"})


@app.route("/pixel_to_world", methods=["POST"])
def pixel_to_world():
    """
    Transform pixel coordinates to world coordinates using calibration.
    Requires calibration to be computed first.

    Request JSON:
        {"pixel_x": 100, "pixel_y": 200}

    Returns:
        {"success": true, "world_x": 0.05, "world_y": 0.10, "world_z": 0.0}
    """
    if not os.path.exists(CALIBRATION_OUTPUT_FILE):
        return jsonify({"success": False, "error": "Calibration not found"}), 400

    try:
        data = request.get_json()
        px, py = data.get("pixel_x"), data.get("pixel_y")

        with open(CALIBRATION_OUTPUT_FILE, 'r') as f:
            calib = json.load(f)

        mtx = np.array(calib["camera_matrix"])
        dist = np.array(calib["distortion_coefficients"])

        # Use first frame's extrinsics as example (in practice, use specific rvec/tvec)
        rvec = np.array(calib["rvecs"][0])
        tvec = np.array(calib["tvecs"][0])

        # Undistort point
        point_undist = cv2.undistortPoints(
            np.array([[[px, py]]], dtype=np.float32),
            mtx, dist, P=mtx
        )

        # Solve PnP for world coordinates (assuming Z=0 plane)
        # Using a simple perspective projection approximation
        fx = mtx[0, 0]
        fy = mtx[1, 1]
        cx = mtx[0, 2]
        cy = mtx[1, 2]

        # Convert to normalized coordinates
        x_norm = (px - cx) / fx
        y_norm = (py - cy) / fy

        # Approximate world coordinates (assuming tvec represents translation from camera to origin)
        scale = tvec[2] / 1.0 if tvec[2] != 0 else 1.0  # depth approximation

        world_x = x_norm * scale + tvec[0]
        world_y = y_norm * scale + tvec[1]

        return jsonify({
            "success": True,
            "pixel": {"x": px, "y": py},
            "world": {"x": float(world_x), "y": float(world_y), "z": float(tvec[2])},
            "calibration_depth_scale": float(scale)
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/save_result", methods=["POST"])
def save_result():
    """Save a segmentation result image to segments folder."""
    try:
        data = request.get_json()
        if not data or 'image_base64' not in data:
            return jsonify({"success": False, "error": "image_base64 required"}), 400

        image_data = base64.b64decode(data['image_base64'])
        timestamp = data.get('timestamp', int(time.time()))
        label = data.get('label', 'result')

        ensure_folder(SEGMENTS_FOLDER)
        filename = f"{label}_{timestamp}.jpg"
        save_path = str(Path(NETWORK_PATH) / SEGMENTS_FOLDER / filename)
        with open(save_path, 'wb') as f:
            f.write(image_data)

        windows_path = save_path.replace("/", "\\")

        return jsonify({
            "success": True,
            "file_path": save_path,
            "file_path_windows": windows_path,
            "timestamp": timestamp
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/save_metadata", methods=["POST"])
def save_metadata():
    """Save metadata JSON to metadata folder."""
    try:
        data = request.get_json()
        if not data or 'metadata' not in data:
            return jsonify({"success": False, "error": "metadata required"}), 400

        metadata = data['metadata']
        timestamp = data.get('timestamp', int(time.time()))
        label = data.get('label', 'meta')

        ensure_folder(METADATA_FOLDER)
        filename = f"{label}_{timestamp}.json"
        save_path = str(Path(NETWORK_PATH) / METADATA_FOLDER / filename)
        with open(save_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        return jsonify({
            "success": True,
            "file_path": save_path,
            "timestamp": timestamp
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/list")
@app.route("/list/<folder>")
def list_files(folder=None):
    """List files in a folder."""
    folders_info = {
        "raw_capture": RAW_CAPTURE_FOLDER,
        "segments": SEGMENTS_FOLDER,
        "metadata": METADATA_FOLDER,
        "calibration": CALIBRATION_FOLDER,
        "cache": CACHE_FOLDER,
    }

    if folder is None:
        result = {}
        for name, path in folders_info.items():
            folder_path = Path(NETWORK_PATH) / path
            if folder_path.exists():
                files = [f.name for f in folder_path.glob("*") if f.is_file()]
                result[name] = {"count": len(files), "files": sorted(files, reverse=True)}
            else:
                result[name] = {"count": 0, "files": []}
        return jsonify(result)

    if folder not in folders_info:
        return jsonify({"error": "Unknown folder"}), 404

    folder_path = Path(NETWORK_PATH) / folders_info[folder]
    if not folder_path.exists():
        return jsonify({"files": [], "count": 0})

    files = [f.name for f in folder_path.glob("*") if f.is_file()]
    return jsonify({"folder": folder, "files": sorted(files, reverse=True), "count": len(files)})


if __name__ == "__main__":
    for folder in [RAW_CAPTURE_FOLDER, SEGMENTS_FOLDER, METADATA_FOLDER, CALIBRATION_FOLDER, CACHE_FOLDER]:
        ensure_folder(folder)
    app.run(host="0.0.0.0", port=8223, debug=False)