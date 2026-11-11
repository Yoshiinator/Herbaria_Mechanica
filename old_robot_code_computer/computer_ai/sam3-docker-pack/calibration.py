"""
Camera Calibration for SAM3
Captures calibration images and computes camera parameters for mapping
pixel coordinates to real-world coordinates.

Usage:
    1. Run calibration_capture.py to capture calibration images
    2. Run calibration_compute.py to compute camera parameters
    3. Save calibration.yml for use in coordinate transformation
"""

import os
import time
import numpy as np
import cv2
import json
from pathlib import Path


# Calibration settings
CALIBRATION_BOARD = (9, 6)  # Inner corners (columns, rows) of chessboard
SQUARE_SIZE = 0.025  # Square size in meters (25mm)
CALIBRATION_IMAGES_FOLDER = "//192.168.1.2/SharedFiles/calibration"
CALIBRATION_OUTPUT_FILE = "//192.168.1.2/SharedFiles/camera_calibration.json"


def capture_calibration_images(camera_index=0, num_images=20):
    """
    Capture calibration images from camera.

    Args:
        camera_index: Camera device index
        num_images: Number of calibration images to capture
    """
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Error: Could not open camera {camera_index}")
        return

    print(f"Opening camera {camera_index}...")
    print(f"Will capture {num_images} calibration images")
    print("Press SPACE to capture an image, ESC to finish early")

    # Create calibration folder
    Path(CALIBRATION_IMAGES_FOLDER).mkdir(parents=True, exist_ok=True)

    image_count = 0
    capturing = True

    while image_count < num_images and capturing:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame")
            break

        # Draw instructions on frame
        display = frame.copy()
        cv2.putText(display, f"Captured: {image_count}/{num_images}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(display, "SPACE: capture, ESC: finish", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Try to detect chessboard corners
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, CALIBRATION_BOARD, None)

        if found:
            # Draw the corners
            cv2.drawChessboardCorners(display, CALIBRATION_BOARD, corners, found)
            cv2.putText(display, "Chessboard detected!", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("Calibration Capture", display)
        key = cv2.waitKey(1) & 0xFF

        if key == 32:  # SPACE
            if found:
                timestamp = int(time.time())
                filename = f"calib_{timestamp}.jpg"
                filepath = os.path.join(CALIBRATION_IMAGES_FOLDER, filename)
                cv2.imwrite(filepath, frame)
                print(f"Captured: {filepath}")
                image_count += 1
            else:
                print("No chessboard detected - move board into view")

        elif key == 27:  # ESC
            capturing = False

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nCaptured {image_count} calibration images")
    print(f"Saved to: {CALIBRATION_IMAGES_FOLDER}")
    return image_count


def compute_calibration():
    """
    Compute camera calibration parameters from captured images.
    """
    folder = Path(CALIBRATION_IMAGES_FOLDER)
    if not folder.exists():
        print(f"Calibration folder not found: {CALIBRATION_IMAGES_FOLDER}")
        return None

    # Prepare object points (0,0,0), (1,0,0), (2,0,0) ....,(8,5,0)
    objp = np.zeros((CALIBRATION_BOARD[0] * CALIBRATION_BOARD[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CALIBRATION_BOARD[0], 0:CALIBRATION_BOARD[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE

    # Arrays to store object points and image points
    objpoints = []  # 3d point in real world space
    imgpoints = []  # 2d points in image plane

    images = sorted(folder.glob("*.jpg"))
    if not images:
        print("No calibration images found")
        return None

    print(f"Processing {len(images)} calibration images...")

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
            print(f"  OK: {img_path.name}")
        else:
            print(f"  FAIL: {img_path.name}")

    if successful < 5:
        print(f"Need at least 5 good images, got {successful}")
        return None

    print(f"\nComputing calibration from {successful} images...")

    # Calibrate camera
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
        "board_size": CALIBRATION_BOARD,
        "rvecs": [r.tolist() for r in rvecs],
        "tvecs": [t.tolist() for t in tvecs]
    }

    with open(CALIBRATION_OUTPUT_FILE, 'w') as f:
        json.dump(calibration_data, f, indent=2)

    print(f"\nCalibration saved to: {CALIBRATION_OUTPUT_FILE}")
    print(f"Camera matrix:\n{mtx}")
    print(f"Distortion coefficients: {dist.flatten()}")
    print(f"Mean reprojection error: {mean_error:.4f} pixels")

    return calibration_data


def load_calibration():
    """Load calibration data from file."""
    if os.path.exists(CALIBRATION_OUTPUT_FILE):
        with open(CALIBRATION_OUTPUT_FILE, 'r') as f:
            return json.load(f)
    return None


def pixel_to_world(point_2D, rvec, tvec, mtx, dist):
    """
    Transform pixel coordinates to world coordinates using calibration.

    Args:
        point_2D: (x, y) pixel coordinates
        rvec: rotation vector from calibration
        tvec: translation vector from calibration
        mtx: camera matrix
        dist: distortion coefficients

    Returns:
        (x, y, z) world coordinates (z=0 for planar assumption)
    """
    # Undistort point
    point_undist = cv2.undistortPoints(np.array([[point_2D]], dtype=np.float32),
                                        mtx, dist, P=mtx)

    # SolvePnP for world coordinates (assuming Z=0)
    imgpts = np.array([[point_undist[0][0]]], dtype=np.float32)
    success, R, t = cv2.solvePnP(np.array([[0,0,0], [1,0,0], [0,1,0]], dtype=np.float32),
                                   imgpts, mtx, dist)

    if success:
        return tuple(t.flatten())
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python calibration.py capture [num_images] - Capture calibration images")
        print("  python calibration.py compute              - Compute calibration parameters")
        print("  python calibration.py info                 - Show current calibration")
        sys.exit(1)

    command = sys.argv[1]

    if command == "capture":
        num = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        capture_calibration_images(0, num)
    elif command == "compute":
        compute_calibration()
    elif command == "info":
        calib = load_calibration()
        if calib:
            print(json.dumps(calib, indent=2))
        else:
            print("No calibration found")
    else:
        print(f"Unknown command: {command}")