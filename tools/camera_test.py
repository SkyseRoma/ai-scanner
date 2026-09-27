"""
Camera test on Raspberry Pi 5.
Captures a frame via rpicam-still (libcamera) and saves to file.
Run: python3 camera_test.py [output.jpg]
"""

import subprocess
import sys
import os
from datetime import datetime


def test_camera_rpicam(output_path):
    """Capture via rpicam-still (libcamera, recommended for RPi5)."""
    cmd = [
        "rpicam-still",
        "-o", output_path,
        "--width", "640",
        "--height", "480",
        "--quality", "85",
        "--immediate",        # no delay
        "--nopreview",        # no GUI
    ]
    print(f"Capturing via rpicam-still...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        print(f"rpicam-still error: {result.stderr}")
        return False
    return os.path.exists(output_path)


def test_camera_picamera2(output_path):
    """Capture via picamera2 (fallback)."""
    try:
        from picamera2 import Picamera2
        print("Capturing via picamera2...")
        picam = Picamera2()
        config = picam.create_still_configuration(main={"size": (640, 480)})
        picam.configure(config)
        picam.start()
        picam.capture_file(output_path)
        picam.stop()
        picam.close()
        return True
    except Exception as e:
        print(f"picamera2 error: {e}")
        return False


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "camera_test.jpg"
    output = os.path.abspath(output)

    print(f"=== RPi5 Camera Test ===")
    print(f"Output: {output}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Try rpicam-still (primary method for RPi5)
    if test_camera_rpicam(output):
        size = os.path.getsize(output)
        print(f"OK! Saved: {output} ({size:,} bytes)")
        return

    # Fallback: picamera2
    print("Trying picamera2...")
    if test_camera_picamera2(output):
        size = os.path.getsize(output)
        print(f"OK! Saved: {output} ({size:,} bytes)")
        return

    print("ERROR: camera not available via rpicam-still or picamera2")
    sys.exit(1)


if __name__ == "__main__":
    main()
