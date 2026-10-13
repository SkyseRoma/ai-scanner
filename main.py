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
from modules.ups import UPS

BTN_PIN = 17
W, H = 320, 240
last_scan_time = 0
SCAN_COOLDOWN = 5
BATT_REFRESH_S = 2.0

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


BAR_H = 18


def frame_to_rgb565(frame):
    """BGR frame → RGB565 bytes for ILI9341."""
    frame = cv2.resize(frame, (W, H))
    b = frame[:, :, 0].astype(np.uint16)
    g = frame[:, :, 1].astype(np.uint16)
    r = frame[:, :, 2].astype(np.uint16)
    rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return ((rgb565 & 0xFF) << 8) | (rgb565 >> 8)


def get_local_ip():
    # Prefer wlan0/eth0 address even without Internet (AP mode uses 10.42.0.1)
    try:
        r = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=2,
        )
        best = ""
        for line in r.stdout.splitlines():
            # 2: wlan0    inet 10.42.0.1/24 brd ...
            if "inet " not in line:
                continue
            parts = line.split()
            ip = parts[3].split("/")[0]
            if "wlan" in line:
                return ip
            best = best or ip
        if best:
            return best
    except Exception:
        pass
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


def get_wifi_signal():
    """Return (ssid, signal_percent). In AP mode SSID is Scanner-AP / AP."""
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "CONNECTION,TYPE,DEVICE", "device", "status"],
            capture_output=True, text=True, timeout=4,
        )
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi":
                conn = parts[0]
                if conn in ("Scanner-AP", "scanner-ap"):
                    return ("AP", 100)
                if conn and conn != "--":
                    # try signal from wifi list
                    r2 = subprocess.run(
                        ["nmcli", "-t", "-f", "IN-USE,SIGNAL,SSID", "device", "wifi", "list"],
                        capture_output=True, text=True, timeout=4,
                    )
                    for line2 in r2.stdout.splitlines():
                        p = line2.split(":")
                        if len(p) >= 3 and p[0] == "*":
                            sig = int(p[1]) if p[1].isdigit() else 0
                            ssid = ":".join(p[2:]) or conn
                            return (ssid[:12], sig)
                    return (conn[:12], 50)
        return ("—", 0)
    except Exception:
        return ("—", 0)


def get_language():
    try:
        import json
        with open("data/settings.json") as f:
            return (json.load(f).get("language") or "ru").upper()[:3]
    except Exception:
        return "RU"


def refresh_net_info(cache):
    now = time.time()
    if now - cache.get("t", 0) < 3.0:
        return cache
    cache["t"] = now
    cache["ip"] = get_local_ip()
    cache["wifi"] = get_wifi_signal()
    cache["lang"] = get_language()
    return cache


def draw_status_bar(frame, net, batt):
    """Bottom status strip: language | IP | WiFi bars | battery."""
    h, w = frame.shape[:2]
    y0 = h - BAR_H
    # bar background
    cv2.rectangle(frame, (0, y0), (w - 1, h - 1), (40, 20, 10), -1)
    cv2.line(frame, (0, y0), (w - 1, y0), (80, 60, 40), 1)

    cyan = (255, 255, 0)
    white = (255, 255, 255)
    green = (0, 255, 0)
    yellow = (0, 255, 255)
    red = (0, 0, 255)

    # language (left)
    lang = net.get("lang") or "—"
    cv2.putText(frame, lang, (6, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, cyan, 1, cv2.LINE_AA)

    # IP
    ip = net.get("ip") or "?"
    cv2.putText(frame, ip, (42, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, white, 1, cv2.LINE_AA)

    # WiFi signal bars
    ssid, sig = net.get("wifi") or ("—", 0)
    bx = w - 120
    bars = 4
    filled = 0
    if sig >= 75:
        filled = 4
    elif sig >= 50:
        filled = 3
    elif sig >= 25:
        filled = 2
    elif sig > 0:
        filled = 1
    for i in range(bars):
        bh = 3 + i * 3
        x = bx + i * 6
        color = green if i < filled else (60, 60, 60)
        if filled and i >= filled:
            color = (60, 60, 60)
        cv2.rectangle(frame, (x, y0 + 14 - bh), (x + 4, y0 + 14), color, -1)
    cv2.putText(frame, f"{ssid}", (bx + 28, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.32, white, 1, cv2.LINE_AA)

    # battery (right)
    pct = 0
    charging = False
    if batt and batt.get("available"):
        pct = int(float(batt.get("percent") or 0))
        charging = bool(batt.get("charging"))
    iw, ih = 18, 9
    x0 = w - iw - 28
    yb = y0 + 5
    outline = white
    cv2.rectangle(frame, (x0, yb), (x0 + iw, yb + ih), outline, 1)
    cv2.rectangle(frame, (x0 + iw, yb + 2), (x0 + iw + 2, yb + ih - 2), outline, -1)
    fill_c = green if pct >= 50 else yellow if pct >= 20 else red
    fill_w = int((iw - 3) * max(0, min(100, pct)) / 100)
    if fill_w > 0:
        cv2.rectangle(frame, (x0 + 1, yb + 1), (x0 + 1 + fill_w, yb + ih - 1), fill_c, -1)
    label = f"{pct}%" + ("+" if charging else "")
    cv2.putText(frame, label, (w - 26, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.35, fill_c, 1, cv2.LINE_AA)


def scan_animation(disp, frame_rgb565, stop_event):
    """Green scanning line animation."""
    line_h = 3
    green565 = np.uint16(0xE007)
    step = 5
    prev_y = -100

    while not stop_event.is_set():
        for y in list(range(0, H - BAR_H - line_h, step)) + list(range(H - BAR_H - line_h, 0, -step)):
            if stop_event.is_set():
                break
            if 0 <= prev_y < H - BAR_H:
                y0, y1 = max(0, prev_y), min(H - BAR_H, prev_y + line_h)
                disp._set_window(0, y0, W - 1, y1)
                disp._send_data(frame_rgb565[y0:y1, :].tobytes())
            y0, y1 = max(0, y), min(H - BAR_H, y + line_h)
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

# Low-battery voice warning. zh uses English audio (Silero has no Chinese).
BATT_WARN_LEVEL = 15.0
BATT_WARN_REPEAT_S = 300.0
BATT_WARN_MSG = {
    "ru": "Внимание! Батарея почти разряжена. Осталось {pct} процентов. Подключите зарядку.",
    "en": "Warning! Battery is low. {pct} percent remaining. Please connect the charger.",
    "zh": "Warning! Battery is low. {pct} percent remaining. Please connect the charger.",
    "es": "¡Advertencia! Batería baja. Queda {pct} por ciento. Conecte el cargador.",
}
TTS_LANG_FOR_WARN = {"zh": "en"}


def maybe_warn_low_battery(tts, batt, state):
    """Speak low-battery warning at most every BATT_WARN_REPEAT_S seconds."""
    if not batt or not batt.get("available"):
        return
    if batt.get("charging"):
        return
    pct = float(batt.get("percent") or 0)
    if pct > BATT_WARN_LEVEL:
        state["warned"] = False
        return
    now = time.time()
    if state.get("warned") and now - state.get("t", 0) < BATT_WARN_REPEAT_S:
        return

    try:
        import json
        with open("data/settings.json") as f:
            lang = (json.load(f).get("language") or "ru").lower()
    except Exception:
        lang = "ru"
    if lang not in BATT_WARN_MSG:
        lang = "en"

    msg = BATT_WARN_MSG[lang].format(pct=int(pct))
    print(f"[!] Low battery ({pct:.0f}%): {msg}")
    try:
        tts.set_language(TTS_LANG_FOR_WARN.get(lang, lang))
        tts.synthesize_and_play(msg, save_path="data/battery_low.wav")
    except Exception as e:
        print(f"Battery warn TTS error: {e}")

    state["warned"] = True
    state["t"] = now


def run():
    ensure_ollama()
    gpt = LLM_engine()
    tts = TTS()
    disp = PiCameraDisplay()
    init_button()

    ups = UPS()
    batt = ups.read_status()
    batt_t = 0.0
    batt_warn_state = {"warned": False, "t": 0.0}
    net_cache = {"t": 0.0, "ip": "?", "wifi": ("—", 0), "lang": "—"}

    cam = Camera(width=160, height=120)
    cam.start()

    question = "Просканируй этот объект. Начни с 'Обнаружен:' или 'Обнаружена:'"

    from modules.web_ui import start_web_ui
    start_web_ui(port=8080)

    print("\n" + "=" * 50)
    print("Scanner started! (picamera2)")
    print("-> GPIO17 button or ENTER — capture")
    print("-> Web UI: http://<IP>:8080")
    if batt and batt.get("available"):
        print(f"-> Battery: {batt.get('percent')}% ({batt.get('voltage_v')}V)")
    else:
        print(f"-> Battery: not available ({ups.error})")
    print("-> Ctrl+C — exit")
    print("=" * 50 + "\n")

    try:
        while True:
            frame = cam.capture_array()
            if frame is None:
                time.sleep(0.05)
                continue

            now = time.time()
            if now - batt_t >= BATT_REFRESH_S:
                batt = ups.read_status()
                batt_t = now
                maybe_warn_low_battery(tts, batt, batt_warn_state)

            try:
                frame_disp = cv2.resize(frame, (W, H))
                refresh_net_info(net_cache)
                draw_status_bar(frame_disp, net_cache, batt)
                frame_raw = frame_to_rgb565(frame_disp)
                disp._set_window()
                disp._send_data(frame_raw.tobytes())
            except Exception:
                frame_raw = None

            global last_scan_time
            if (check_button() or check_keyboard()) and (now - last_scan_time > SCAN_COOLDOWN):
                last_scan_time = now
                print("\n[!] Capture!")

                timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
                session_dir = os.path.join("data", "database", timestamp)
                os.makedirs(session_dir, exist_ok=True)

                image_path = os.path.join(session_dir, "shot.jpg")
                text_path = os.path.join(session_dir, "answer.txt")
                audio_path = os.path.join(session_dir, "audio.wav")

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
        ups.close()
        if _gpio is not None:
            lgpio.gpiochip_close(_gpio)
        disp.cleanup()


if __name__ == "__main__":
    run()