"""
Camera for Raspberry Pi 5 (picamera2).
"""

import os
os.environ["LIBCAMERA_LOG_LEVELS"] = "*:ERROR"

import numpy as np
import cv2
import time
from picamera2 import Picamera2


class Camera:
    """Camera via picamera2."""

    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self._cam = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._cam = Picamera2()
        config = self._cam.create_video_configuration(
            main={"size": (self.width, self.height), "format": "BGR888"}
        )
        self._cam.configure(config)
        self._cam.start()
        self._running = True
        time.sleep(0.5)

    def stop(self):
        self._running = False
        if self._cam is not None:
            try:
                self._cam.stop()
                self._cam.close()
            except Exception:
                pass
            self._cam = None

    def capture_array(self):
        if not self._running or self._cam is None:
            return None
        try:
            frame = self._cam.capture_array()
            if frame is None:
                return None
            frame = cv2.flip(frame, -1)
            # BGR888 actually outputs RGB — swap needed
            frame = frame[:, :, ::-1]  # RGB → BGR
            return frame
        except Exception:
            return None

    def capture_file(self, path):
        frame = self.capture_array()
        if frame is not None:
            return cv2.imwrite(path, frame)
        return False


if __name__ == "__main__":
    cam = Camera()
    cam.start()
    print("Testing picamera2 camera...")

    frames = 0
    start = time.time()
    duration = 5

    while time.time() - start < duration:
        frame = cam.capture_array()
        if frame is not None:
            frames += 1

    elapsed = time.time() - start
    fps = frames / elapsed
    print(f"Captured {frames} frames in {elapsed:.1f}s = {fps:.1f} FPS")

    if frame is not None:
        cv2.imwrite("camera_test.jpg", frame)
        print(f"Saved: camera_test.jpg ({frame.shape})")

    cam.stop()
    print("Done")