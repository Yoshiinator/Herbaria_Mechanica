"""
SSH Camera Capture Service
Connects to remote machine via SSH and captures images using OpenCV.
"""

import base64
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import paramiko
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# Configuration
SSH_HOST = "192.168.1.2"
SSH_USER = "mahim"
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "your_password_here")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", None)

NETWORK_PATH = "//192.168.1.2/SharedFiles"
SAVE_FOLDER = "captures"

OUTPUT_BASE_PATH = os.path.join(NETWORK_PATH, SAVE_FOLDER)


def ensure_directory_exists(sftp, remote_path: str) -> None:
    """Create remote directory if it doesn't exist."""
    dirs = remote_path.split("/")
    current_dir = ""
    for d in dirs:
        if d:
            current_dir += "/" + d
            try:
                sftp.stat(current_dir)
            except FileNotFoundError:
                sftp.mkdir(current_dir)
                print(f"Created remote directory: {current_dir}")


def capture_image_via_ssh(camera_index: int = 0) -> tuple[bytes, str]:
    """
    Connect to remote machine via SSH and capture image using OpenCV.

    Args:
        camera_index: Camera index (default 0)

    Returns:
        Tuple of (image_bytes, filename)
    """
    timestamp = int(time.time())
    filename = f"capture_{timestamp}.jpg"
    remote_path = f"{NETWORK_PATH}/{SAVE_FOLDER}/{filename}"

    # Local temp file for capture script
    local_script = f"/tmp/capture_script_{timestamp}.sh"
    local_output = f"/tmp/captured_{timestamp}.jpg"

    # Create capture script that runs on remote machine
    capture_script = f'''#!/bin/bash
import cv2
import sys

cam_idx = {camera_index}
cap = cv2.VideoCapture(cam_idx)

if not cap.isOpened():
    print(f"Error: Could not open camera {{cam_idx}}", file=sys.stderr)
    sys.exit(1)

ret, frame = cap.read()
cap.release()

if not ret:
    print("Error: Failed to capture frame", file=sys.stderr)
    sys.exit(1)

cv2.imwrite("{local_output}", frame)
print("OK")
'''

    # Write script locally
    with open(local_script, "w") as f:
        f.write(capture_script)

    try:
        # Connect via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if SSH_KEY_PATH:
            ssh.connect(
                SSH_HOST,
                username=SSH_USER,
                key_filename=SSH_KEY_PATH,
                timeout=10
            )
        else:
            ssh.connect(
                SSH_HOST,
                username=SSH_USER,
                password=SSH_PASSWORD,
                timeout=10
            )

        # Ensure output directory exists on remote
        sftp = ssh.open_sftp()
        remote_save_dir = f"{NETWORK_PATH}/{SAVE_FOLDER}"
        try:
            sftp.stat(remote_save_dir)
        except FileNotFoundError:
            sftp.mkdir(remote_save_dir)
            print(f"Created remote directory: {remote_save_dir}")

        # Transfer capture script
        sftp.put(local_script, local_script)

        # Run capture script on remote
        # Using Python directly via SSH instead of script file
        python_cmd = f'''python3 -c '
import cv2
import sys

cam_idx = {camera_index}
cap = cv2.VideoCapture(cam_idx)

if not cap.isOpened():
    print(f"Error: Could not open camera {{cam_idx}}", file=sys.stderr)
    sys.exit(1)

ret, frame = cap.read()
cap.release()

if not ret:
    print("Error: Failed to capture frame", file=sys.stderr)
    sys.exit(1)

cv2.imwrite("{local_output}", frame)
print("OK")
' 2>&1'''

        stdin, stdout, stderr = ssh.exec_command(python_cmd)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()

        if error or output != "OK":
            raise Exception(f"Capture failed: {error or output}")

        # Read the captured image
        with open(local_output, "rb") as f:
            image_bytes = f.read()

        # Upload to network path
        sftp.put(local_output, remote_path)
        print(f"Image saved to: {remote_path}")

        # Cleanup local files
        os.remove(local_script)
        os.remove(local_output)

        return image_bytes, remote_path

    finally:
        try:
            sftp.close()
        except:
            pass
        try:
            ssh.close()
        except:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("SSH Camera Capture Service Starting")
    print(f"SSH Host: {SSH_USER}@{SSH_HOST}")
    print(f"Output Path: {OUTPUT_BASE_PATH}")
    yield
    print("SSH Camera Capture Service Shutting Down")


app = FastAPI(
    title="SSH Camera Capture API",
    description="Capture images via SSH from remote camera",
    version="1.0.0",
    lifespan=lifespan,
)


class CaptureResponse(BaseModel):
    success: bool
    file_path: str
    file_path_unix: str
    message: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "SSH Camera Capture",
        "ssh_host": SSH_HOST,
        "ssh_user": SSH_USER,
        "output_path": OUTPUT_BASE_PATH,
    }


@app.post("/capture", response_model=CaptureResponse)
async def capture_image(camera_index: int = 0):
    """
    Capture an image from the remote camera via SSH.

    - **camera_index**: Camera index (default 0)
    """
    try:
        image_bytes, remote_path = capture_image_via_ssh(camera_index)

        # Convert Windows path to Unix path for API response
        unix_path = remote_path.replace("\\", "/").replace("//", "/")

        return CaptureResponse(
            success=True,
            file_path=remote_path,
            file_path_unix=unix_path,
            message=f"Image captured and saved successfully ({len(image_bytes)} bytes)",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/capture", response_model=CaptureResponse)
async def capture_image_get(camera_index: int = 0):
    """
    Capture an image from the remote camera via SSH (GET method).

    - **camera_index**: Camera index (default 0)
    """
    return await capture_image(camera_index)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8223)
