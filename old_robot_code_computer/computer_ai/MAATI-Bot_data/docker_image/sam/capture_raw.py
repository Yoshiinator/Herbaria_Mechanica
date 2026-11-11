import cv2
import time
import os

cap = cv2.VideoCapture(0)
ret, frame = cap.read()
cap.release()

if ret:
    timestamp = int(time.time())
    path = f"//192.168.1.2/SharedFiles/raw_capture/capture_{timestamp}.jpg"
    cv2.imwrite(path, frame)
    print(f"SAVED:{path}")
else:
    print("ERROR:Failed to capture")
