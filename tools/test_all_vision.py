#!/usr/bin/env python3
"""Test vision models on RPi5 with unloading between tests."""

import os, sys, time, gc, base64, requests

os.environ["LIBCAMERA_LOG_LEVELS"] = "*:ERROR"

PROMPT = "PDA scanner. Write in Russian. Start with: НАЙДЕН: [object name]. Then material+purpose or species+habitat. Then one fact. Max 3 sentences total. Never write На изображении."
USER_MSG = "Scan this object."
OLLAMA_URL = "http://localhost:11434/api/chat"
MODELS = ["qwen3.5:0.8b", "moondream", "gemma3:4b", "gemma4-e2b"]


def unload_all():
    """Unload ALL models from VRAM/RAM."""
    for m in MODELS:
        try:
            requests.post("http://localhost:11434/api/generate",
                          json={"model": m, "keep_alive": 0}, timeout=30)
        except:
            pass
    time.sleep(5)
    os.system("sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null")
    gc.collect()
    time.sleep(2)


def capture_image():
    from picamera2 import Picamera2
    import cv2
    cam = Picamera2()
    cam.configure(cam.create_video_configuration(main={"size": (640,480), "format": "BGR888"}))
    cam.start(); time.sleep(1)
    frame = cam.capture_array()
    cam.stop(); cam.close(); del cam; gc.collect()
    if frame is not None:
        frame = cv2.flip(frame, -1)[:,:,::-1]
        path = "/tmp/test_scan.jpg"
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
        resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
        elapsed = time.time() - start
        if resp.status_code == 200:
            return elapsed, resp.json().get("message",{}).get("content","").strip()
        else:
            return elapsed, f"ERROR {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return time.time() - start, f"ERROR: {e}"


def main():
    print("="*60)
    print("VISION MODEL TEST ON RASPBERRY PI 5 (8GB)")
    print("="*60)

    print("\n[1] Capturing frame...")
    img = capture_image()
    if not img:
        print("Camera not responding!"); return
    print(f"  Saved: {img}")

    results = []
    for i, model in enumerate(MODELS, 2):
        print(f"\n[{i}/{len(MODELS)+1}] {model}")
        print("  Unloading previous models...")
        unload_all()
        mem = os.popen("free -h | grep Mem").read().split()
        print(f"  Memory: {mem[2]} used / {mem[3]} free")
        print("  Generating...")
        elapsed, answer = test_model(model, img)
        results.append({"model": model, "time": elapsed, "answer": answer})
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Answer: {answer[:400]}")
        print("  "+"-"*50)

    unload_all()

    print("\n"+"="*60)
    print("SUMMARY TABLE:")
    print(f"{'Model':<20} {'Time':>8} {'OK':>4}")
    print("-"*35)
    for r in results:
        ok = "YES" if "ERROR" not in r["answer"] else "NO"
        print(f"{r['model']:<20} {r['time']:>6.1f}s {ok:>4}")

    print("\nDETAILED RESPONSES:")
    for r in results:
        print(f"\n{'='*50}")
        print(f"{r['model']} ({r['time']:.1f}s)")
        print("-"*50)
        print(r['answer'])

if __name__ == "__main__":
    main()
