import os
import sys
import select
import time
import subprocess
import threading
import cv2
import numpy as np
import lgpio
from modules import *

BTN_PIN = 17
W, H = 320, 240
last_scan_time = 0
SCAN_COOLDOWN = 5

_gpio = None


def init_button():
    global _gpio
    _gpio = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_input(_gpio, BTN_PIN, lgpio.SET_PULL_UP)


def check_button():
    return lgpio.gpio_read(_gpio, BTN_PIN) == 0


def check_keyboard():
    if not sys.stdin.isatty():
        return False
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if ready:
        sys.stdin.readline()
        return True
    return False


def ensure_ollama():
    import requests
    try:
        requests.get("http://localhost:11434/api/tags", timeout=2)
        print("Ollama: already running")
        return
    except Exception:
        pass
    print("Ollama: starting...")
    env = os.environ.copy()
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    for _ in range(20):
        time.sleep(1)
        try:
            requests.get("http://localhost:11434/api/tags", timeout=2)
            print("Ollama: ready")
            return
        except Exception:
            pass
    print("Ollama: failed to start!")


def frame_to_rgb565(frame):
    """BGR frame → RGB565 bytes for ILI9341."""
    frame = cv2.resize(frame, (W, H))
    b = frame[:, :, 0].astype(np.uint16)
    g = frame[:, :, 1].astype(np.uint16)
    r = frame[:, :, 2].astype(np.uint16)
    rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return ((rgb565 & 0xFF) << 8) | (rgb565 >> 8)


def scan_animation(disp, frame_rgb565, stop_event):
    """Green scanning line animation."""
    line_h = 3
    green565 = np.uint16(0xE007)
    step = 5
    prev_y = -100

    while not stop_event.is_set():
        for y in list(range(0, H - line_h, step)) + list(range(H - line_h, 0, -step)):
            if stop_event.is_set():
                break
            if 0 <= prev_y < H:
                y0, y1 = max(0, prev_y), min(H, prev_y + line_h)
                disp._set_window(0, y0, W - 1, y1)
                disp._send_data(frame_rgb565[y0:y1, :].tobytes())
            y0, y1 = max(0, y), min(H, y + line_h)
            line = np.full((y1 - y0, W), green565, dtype=np.uint16)
            disp._set_window(0, y0, W - 1, y1)
            disp._send_data(line.tobytes())
            prev_y = y
            time.sleep(0.015)

    disp._set_window()
    disp._send_data(frame_rgb565.tobytes())


LANG_QUESTIONS = {
    "ru": "Просканируй этот объект. Опиши на русском языке.",
    "en": "Scan this object. Describe in English.",
    "zh": "扫描此对象。用中文描述。",
    "es": "Escanea este objeto. Describe en español.",
}


def run():
    ensure_ollama()
    gpt = LLM_engine()
    tts = TTS()
    disp = PiCameraDisplay()
    init_button()

    cam = Camera(width=160, height=120)
    cam.start()

    question = "Просканируй этот объект. Начни с 'Обнаружен:' или 'Обнаружена:'"

    from modules.web_ui import start_web_ui
    start_web_ui(port=8080)

    print("\n" + "=" * 50)
    print("Scanner started! (picamera2)")
    print("-> GPIO17 button or ENTER — capture")
    print("-> Web UI: http://<IP>:8080")
    print("-> Ctrl+C — exit")
    print("=" * 50 + "\n")

    try:
        while True:
            frame = cam.capture_array()
            if frame is None:
                time.sleep(0.05)
                continue

            try:
                frame_raw = frame_to_rgb565(frame)
                disp._set_window()
                disp._send_data(frame_raw.tobytes())
            except Exception:
                frame_raw = None

            global last_scan_time
            now = time.time()
            if (check_button() or check_keyboard()) and (now - last_scan_time > SCAN_COOLDOWN):
                last_scan_time = now
                print("\n[!] Capture!")

                timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
                session_dir = os.path.join("data", "database", timestamp)
                os.makedirs(session_dir, exist_ok=True)

                image_path = os.path.join(session_dir, "shot.jpg")
                text_path = os.path.join(session_dir, "answer.txt")
                audio_path = os.path.join(session_dir, "audio.mp3")

                # Stop camera, capture hi-res frame
                cam.stop()
                time.sleep(0.3)
                hi_cam = Camera(width=640, height=480)
                hi_cam.start()
                time.sleep(0.3)
                hi_frame = hi_cam.capture_array()
                hi_cam.stop()
                del hi_cam

                if hi_frame is not None:
                    cv2.imwrite(image_path, hi_frame)
                else:
                    cv2.imwrite(image_path, frame)
                print(f"Saved: {image_path}")

                # Restart main camera
                cam.start()

                # Animation
                stop_anim = threading.Event()
                if frame_raw is not None:
                    anim = threading.Thread(target=scan_animation, args=(disp, frame_raw, stop_anim), daemon=True)
                    anim.start()

                # AI + TTS
                print("Requesting AI...")
                gpt.config = gpt.read_settings()
                lang = gpt.config.get("language", "ru")
                question = LANG_QUESTIONS.get(lang, LANG_QUESTIONS["ru"])
                tts.set_language(lang)

                t_start = time.time()
                answer = gpt.request_answer(question, image_path)
                t_ai = time.time() - t_start
                print(f"Response ({t_ai:.1f}s): {answer}")

                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(answer)

                try:
                    tts.synthesize_and_play(answer, save_path=audio_path)
                except TypeError:
                    tts.synthesize_and_play(answer)

                stop_anim.set()
                time.sleep(0.1)
                print(f"Done: {session_dir}")

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        cam.stop()
        if _gpio is not None:
            lgpio.gpiochip_close(_gpio)
        disp.cleanup()


if __name__ == "__main__":
    run()