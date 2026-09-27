"""
MJPEG stream server for Raspberry Pi camera (RPi5).
Capture via rpicam-still --timelapse.
Run: python3 camera_stream.py [--port 8080]
Open: http://<RPi_IP>:8080
"""

import subprocess
import threading
import http.server
import socketserver
import argparse
import signal
import sys
import os
import time

frame_buffer = bytearray()
frame_lock = threading.Lock()
frame_ready = threading.Event()


def capture_loop(width, height, fps):
    """Continuous frame capture via rpicam-still --timelapse."""
    global frame_buffer
    interval_ms = max(100, int(1000 / fps))  # min 100ms between frames

    while True:
        cmd = [
            "rpicam-still",
            "--width", str(width),
            "--height", str(height),
            "--quality", "85",
            "--immediate",
            "--nopreview",
            "-o", "-",  # stdout
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0 and len(result.stdout) > 100:
                # Check that it's a JPEG (starts with FFD8)
                if result.stdout[:2] == b'\xff\xd8':
                    with frame_lock:
                        frame_buffer.clear()
                        frame_buffer.extend(result.stdout)
                    frame_ready.set()
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            print(f"Capture error: {e}")
            time.sleep(1)

        time.sleep(interval_ms / 1000.0)


class StreamHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"""<!DOCTYPE html>
<html><head><title>Scanner Camera</title>
<style>
body{margin:0;background:#111;display:flex;justify-content:center;align-items:center;height:100vh}
img{max-width:100%;max-height:100%}
</style></head><body><img src="/stream" /></body></html>""")

        elif self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                prev = b''
                while True:
                    frame_ready.wait(timeout=10)
                    with frame_lock:
                        data = bytes(frame_buffer) if frame_buffer else None
                    if data and data != prev:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(data)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                        prev = data
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == '/snapshot':
            frame_ready.wait(timeout=10)
            with frame_lock:
                data = bytes(frame_buffer) if frame_buffer else None
            if data:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(503)
                self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=10, help="Frames per second (1-30)")
    args = parser.parse_args()

    t = threading.Thread(target=capture_loop, args=(args.width, args.height, args.fps), daemon=True)
    t.start()

    print(f"Waiting for camera...")
    if not frame_ready.wait(timeout=15):
        print("Camera not responding!")

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("0.0.0.0", args.port), StreamHandler)
    print(f"Stream: http://0.0.0.0:{args.port}")
    print(f"Frame:  http://0.0.0.0:{args.port}/snapshot")

    signal.signal(signal.SIGINT, lambda s, f: (server.shutdown(), sys.exit(0)))
    server.serve_forever()

if __name__ == "__main__":
    main()
