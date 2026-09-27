"""
AI scanner with web interface.
Camera + Ollama (qwen3.5:0.8b) + MJPEG stream + scan button.

Run: python3 scanner_web.py
Open: http://<RPi_IP>:9090
"""

import subprocess
import threading
import requests
import json
import http.server
import socketserver
import json
import base64
import os
import time
import signal
import sys
from datetime import datetime

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# ── Configuration ──────────────────────────────────────────────────────
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 5
HTTP_PORT = 9090
OLLAMA_URL = "http://localhost:11434/v1"
OLLAMA_IP = "localhost"
OLLAMA_PORT = "11434"
OLLAMA_MODEL = "qwen3.5:0.8b"
SCANNER_PROMPT = (
    "Ты — портативный сканер из игры Subnautica. Когда тебе показывают объект, "
    "сначала дай ему идентификатор (например: «Обнаружен: [название объекта]»), "
    "затем опиши его свойства, характеристики, возможное происхождение или назначение. "
    "Добавь интересный факт или наблюдение. "
    "Стиль: голос PDA из Subnautica — сухой, научный, слегка отстранённый, как будто "
    "анализируешь инопланетный объект. Не начинай с «На изображении» или «На фото». "
    "Не описывай что видишь — сканируй и классифицируй объект. "
    "2-4 коротких предложения. Только русский."
)

# ── Global state ───────────────────────────────────────────────────────
frame_buffer = bytearray()
frame_lock = threading.Lock()
frame_ready = threading.Event()
frame_count = 0
capture_active = threading.Event()
capture_active.set()  # capture active by default

last_scan_result = ""
last_scan_time = ""
scan_lock = threading.Lock()
scan_in_progress = False

ollama_client = None
if HAS_OPENAI:
    try:
        ollama_client = OpenAI(base_url=OLLAMA_URL, api_key="ollama", timeout=600.0)
    except Exception:
        pass


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Camera capture ─────────────────────────────────────────────────────
def capture_loop():
    """Continuous MJPEG capture via rpicam-vid (single process)."""
    global frame_buffer, frame_count

    log("Camera thread started (rpicam-vid MJPEG)")

    cmd = [
        "rpicam-vid",
        "--width", str(CAMERA_WIDTH),
        "--height", str(CAMERA_HEIGHT),
        "--codec", "mjpeg",
        "--quality", "70",
        "--framerate", "30",
        "--nopreview",
        "-o", "-",
    ]

    proc = None
    buf = bytearray()

    while True:
        # Pause capture during scanning
        if not capture_active.is_set():
            if proc is not None:
                proc.terminate()
                proc.wait()
                proc = None
                log("Capture paused (scanning)")
            capture_active.wait()  # wait until scanning finishes
            log("Capture resumed")
            continue

        # Restart process on failure
        if proc is None or proc.poll() is not None:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                log(f"rpicam-vid started (PID {proc.pid})")
                buf.clear()
            except Exception as e:
                log(f"rpicam-vid start error: {e}")
                time.sleep(2)
                continue

        try:
            chunk = proc.stdout.read(65536)
            if not chunk:
                proc = None
                time.sleep(0.5)
                continue
        except Exception:
            proc = None
            time.sleep(0.5)
            continue

        buf.extend(chunk)

        # Extract the last complete JPEG from buffer
        while True:
            start = buf.find(b'\xff\xd8')
            if start == -1:
                buf.clear()
                break
            end = buf.find(b'\xff\xd9', start + 2)
            if end == -1:
                # Wait for remaining data
                if start > 0:
                    buf = buf[start:]
                break
            jpeg = bytes(buf[start:end + 2])
            buf = buf[end + 2:]

            with frame_lock:
                frame_buffer.clear()
                frame_buffer.extend(jpeg)
            frame_count += 1
            frame_ready.set()

            if frame_count == 1:
                log(f"First frame: {len(jpeg)} bytes")
            elif frame_count % 100 == 0:
                log(f"Frames: {frame_count}")


# ── AI scanning ────────────────────────────────────────────────────────
def scan_image(image_bytes):
    """Send frame to Ollama via native API and get description."""
    global last_scan_result, last_scan_time, scan_in_progress

    # Pause capture, free resources for the model
    capture_active.clear()
    scan_in_progress = True
    img_kb = len(image_bytes) / 1024
    log(f"Scanning: frame {img_kb:.0f} KB, encoding base64...")

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        log(f"Scanning: base64 ready ({len(b64)//1024} KB), requesting {OLLAMA_MODEL}...")
        t0 = time.time()

        resp = requests.post(
            f"http://{OLLAMA_IP}:{OLLAMA_PORT}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SCANNER_PROMPT},
                    {"role": "user", "content": "Что на этом изображении? Ответь на русском.",
                     "images": [b64]},
                ],
                "stream": False,
                "think": False,
                "options": {"num_predict": 300, "temperature": 0.3},
            },
            timeout=300,
        )
        elapsed = time.time() - t0
        data = resp.json()
        result = data.get("message", {}).get("content", "").strip()
        log(f"Scanning: response received in {elapsed:.1f}s, {len(result)} characters")
        log(f"  -> {result[:120]}...")

    except Exception as e:
        elapsed = time.time() - t0
        result = f"Error: {e}"
        log(f"Ollama ERROR ({elapsed:.1f}s): {e}")

    with scan_lock:
        last_scan_result = result
        last_scan_time = datetime.now().strftime("%H:%M:%S")
    scan_in_progress = False
    capture_active.set()  # resume capture
    return result


# ── HTTP server ────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Scanner - Subnautica AI</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a1a; color:#00ff88; font-family:'Courier New',monospace; }
.wrap { max-width:900px; margin:0 auto; padding:20px; }
h1 { text-align:center; font-size:1.5em; margin:15px 0; color:#00ffaa;
     text-shadow:0 0 10px #00ff8844; }
.cam-box { position:relative; background:#111; border:2px solid #00ff8844;
           border-radius:8px; overflow:hidden; }
.cam-box img { width:100%; display:block; }
#snapshot { display:none; width:100%; }
.scan-line { display:none; position:absolute; left:0; right:0; height:4px;
             background:linear-gradient(90deg, transparent, #00ff88, transparent);
             box-shadow:0 0 15px #00ff88, 0 0 30px #00ff8888;
             animation:scanMove 2s ease-in-out infinite; z-index:10; }
@keyframes scanMove {
  0%,100% { top:0; }
  50% { top:calc(100% - 4px); }
}
.scan-btn { display:block; width:100%; padding:15px; margin-top:15px;
            background:#00ff8822; border:2px solid #00ff88; color:#00ff88;
            font-family:inherit; font-size:1.2em; cursor:pointer;
            border-radius:8px; transition:all .2s; }
.scan-btn:hover { background:#00ff8844; }
.scan-btn:disabled { opacity:.4; cursor:wait; }
.result-box { margin-top:15px; padding:15px; background:#111;
              border:2px solid #00ff8844; border-radius:8px;
              min-height:80px; white-space:pre-wrap; line-height:1.5; }
.result-box.scanning { border-color:#ffaa00; color:#ffaa00; }
.status { text-align:center; margin-top:10px; font-size:.85em; color:#557; }
</style>
</head>
<body>
<div class="wrap">
<h1>SUBNAUTICA SCANNER</h1>
<div class="cam-box">
  <img id="stream" src="/stream" />
  <img id="snapshot" />
  <div class="scan-line" id="scanline"></div>
</div>
<button class="scan-btn" id="btn" onclick="doScan()">SCAN</button>
<div class="result-box" id="result">Waiting for scan...</div>
<div class="status" id="status">Camera active</div>
</div>
<script>
async function doScan() {
  const btn = document.getElementById('btn');
  const res = document.getElementById('result');
  const stream = document.getElementById('stream');
  const snap = document.getElementById('snapshot');
  const line = document.getElementById('scanline');

  // Freeze frame: hide stream, show snapshot
  snap.src = '/snapshot?' + Date.now();
  stream.style.display = 'none';
  snap.style.display = 'block';
  line.style.display = 'block';

  btn.disabled = true;
  btn.textContent = 'SCANNING...';
  res.className = 'result-box scanning';
  res.textContent = 'Analyzing image... (first request may take ~1 min)';

  try {
    const r = await fetch('/scan', {method:'POST'});
    const d = await r.json();
    res.className = 'result-box';
    res.textContent = d.result || 'No response';
    document.getElementById('status').textContent =
      'Last scan: ' + d.time;
  } catch(e) {
    res.className = 'result-box';
    res.textContent = 'Error: ' + e;
  }

  // Restore stream
  line.style.display = 'none';
  snap.style.display = 'none';
  stream.style.display = 'block';
  stream.src = '/stream?' + Date.now();
  btn.disabled = false;
  btn.textContent = 'SCAN';
}
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]  # strip query parameters

        if path == '/':
            log(f"HTTP GET / -- main page ({self.client_address[0]})")
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())

        elif path == '/stream':
            log(f"HTTP GET /stream -- stream connection ({self.client_address[0]})")
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            sent = 0
            try:
                prev = b''
                while True:
                    frame_ready.wait(timeout=5)
                    with frame_lock:
                        data = bytes(frame_buffer) if frame_buffer else None
                    if data and data != prev:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(data)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                        prev = data
                        sent += 1
                        if sent == 1:
                            log(f"Stream: first frame sent ({len(data)} bytes)")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                log(f"Stream: client disconnected ({self.client_address[0]})")

        elif path == '/snapshot':
            log(f"HTTP GET /snapshot ({self.client_address[0]})")
            frame_ready.wait(timeout=5)
            with frame_lock:
                data = bytes(frame_buffer) if frame_buffer else None
            if data:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(503)
                self.end_headers()

        elif path == '/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            with scan_lock:
                resp = {"result": last_scan_result, "time": last_scan_time,
                        "scanning": scan_in_progress}
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/scan':
            log(f"HTTP POST /scan -- scan request ({self.client_address[0]})")
            with frame_lock:
                data = bytes(frame_buffer) if frame_buffer else None
            if not data:
                log("ERROR: no frame available for scanning")
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"error":"no frame"}')
                return

            result = scan_image(data)
            with scan_lock:
                resp = {"result": result, "time": last_scan_time}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())
        else:
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    log("Starting Scanner Web UI...")

    # Start camera capture
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()

    log("Waiting for camera...")
    if not frame_ready.wait(timeout=15):
        log("WARNING: camera did not respond within 15s")
    else:
        log(f"Camera ready: {CAMERA_WIDTH}x{CAMERA_HEIGHT}")

    if ollama_client:
        log(f"Ollama: {OLLAMA_MODEL} (loaded on first request)")
    else:
        log("WARNING: openai not installed -- scanning unavailable")

    server = ThreadedHTTPServer(("0.0.0.0", HTTP_PORT), Handler)

    log(f"{'='*45}")
    log(f"  Web UI: http://0.0.0.0:{HTTP_PORT}")
    log(f"  Camera: {CAMERA_WIDTH}x{CAMERA_HEIGHT} @ {CAMERA_FPS}fps")
    log(f"  Model: {OLLAMA_MODEL}")
    log(f"{'='*45}")
    log("Ready. Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping via Ctrl+C")
    finally:
        server.server_close()
        log("Server stopped")


if __name__ == "__main__":
    main()
