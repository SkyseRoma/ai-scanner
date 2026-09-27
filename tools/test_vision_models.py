#!/usr/bin/env python3
"""Test vision models on RPi5: speed + quality."""

import os, sys, time, gc, base64, requests

os.environ["LIBCAMERA_LOG_LEVELS"] = "*:ERROR"

from picamera2 import Picamera2
import cv2

PROMPT = "PDA scanner. Write in Russian. Start with: НАЙДЕН: [object name]. Then material+purpose or species+habitat. Then one fact. Max 3 sentences total. Never write На изображении."
USER_MSG = "Scan this object."
OLLAMA_URL = "http://localhost:11434/api/chat"

MODELS = ["qwen3.5:0.8b", "moondream"]


def free_memory():
    try:
        requests.post("http://localhost:11434/api/generate",
                      json={"model": "", "keep_alive": 0}, timeout=10)
    except:
        pass
    gc.collect()
    time.sleep(3)


def capture_image(path="/tmp/test_scan.jpg"):
    cam = Picamera2()
    config = cam.create_video_configuration(main={"size": (640, 480), "format": "BGR888"})
    cam.configure(config)
    cam.start()
    time.sleep(1)
    frame = cam.capture_array()
    cam.stop(); cam.close(); del cam; gc.collect()
    if frame is not None:
        frame = cv2.flip(frame, -1)
        frame = frame[:, :, ::-1]
        cv2.imwrite(path, frame)
        return path
    return None


def test_model(model, image_path):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": USER_MSG, "images": [b64]},
        ],
        "stream": False, "think": False,
        "options": {"num_predict": 120, "temperature": 0.7},
    }
    start = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        elapsed = time.time() - start
        return elapsed, resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return time.time() - start, f"ERROR: {e}"


def main():
    print("=" * 60)
    print("VISION MODEL TEST ON RASPBERRY PI 5 (8GB)")
    print("=" * 60)

    print("\n[1] Capturing frame...")
    img = capture_image()
    if not img:
        print("Camera not responding!"); return
    print(f"  Saved: {img}")

    results = []
    for i, model in enumerate(MODELS, 2):
        print(f"\n[{i}] {model}")
        print("  Freeing memory..."); free_memory()
        print("  Generating...")
        elapsed, answer = test_model(model, img)
        results.append({"model": model, "time": elapsed, "answer": answer})
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Answer: {answer[:300]}")
        print("  " + "-" * 50)

    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"{'Model':<20} {'Time':>8}")
    print("-" * 30)
    for r in results:
        print(f"{r['model']:<20} {r['time']:>6.1f}s")

    print("\nRESPONSES:")
    for r in results:
        print(f"\n--- {r['model']} ({r['time']:.1f}s) ---")
        print(r['answer'])
    free_memory()


if __name__ == "__main__":
    main()
