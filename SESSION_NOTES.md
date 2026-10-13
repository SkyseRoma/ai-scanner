## RPi5 Connection
- **OS**: Raspberry Pi OS Lite (Debian Trixie, aarch64, no desktop)
- **Hostname**: `scanner` → `ssh pi@scanner.local` (alias in ~/.ssh/config: `ssh scanner`)
- **User**: `pi` (NOT `airpi2`)
- **SSH key**: `~/.ssh/id_ed25519` (ed25519, passwordless)
- **IP (WiFi, SkyNet)**: 192.168.1.21 (wlan0, DHCP) — primary
- **IP (hotspot Scanner-AP)**: 10.42.0.1 (when no known network)
- **WiFi**: NetworkManager profile `SkyNet` (`sudo nmcli device wifi connect "SSID" password "..."`)
- **Hotspot**: SSID `Scanner-AP`, password `scanner123` (or wifi_ap_* in settings.json)
- **SSH**: `ssh scanner` / `ssh pi@192.168.1.21` / `ssh pi@10.42.0.1` (AP) / `ssh pi@scanner.local`
- **VSCode Remote-SSH**: `scanner` or `pi@192.168.1.21`
- **sudo**: NOPASSWD configured (`/etc/sudoers.d/010_pi-nopasswd`)
- **Project**: `/home/pi/PROJECTS/scanner/`
- **Python**: 3.13.5 (system, no conda)
- **Run manually**: `python3 main.py`
- **Run as service**: `sudo systemctl start scanner`
- **Web UI**: `http://scanner.local:8080` (port 8080)

## Project Structure
```
scanner/
├── main.py                    # camera → display → status bar → scan → LLM → TTS
├── run.sh                     # launcher
├── README.md / README_EN.md / README_ES.md / README_ZH.md
├── modules/
│   ├── camera.py              # picamera2, BGR888→BGR swap, 180° flip
│   ├── disp.py                # ILI9341 via SPI0, lgpio (not RPi.GPIO)
│   ├── llm.py                 # Ollama API /api/chat
│   ├── tts.py                 # Silero TTS, paplay→aplay fallback
│   ├── ups.py                 # Waveshare UPS 3S / INA219 I2C battery monitor
│   ├── wifi.py                # NetworkManager nmcli: scan/connect/hotspot
│   ├── web_ui.py              # Web UI: scans, chat, settings, logs, battery, Wi-Fi
│   └── __init__.py
├── data/
│   ├── settings.json          # model, prompt, language, Ollama, wifi_ap_*
│   └── database/              # scan sessions (shot.jpg, answer.txt, audio.wav)
├── tools/                     # test_i2s, test_ups, test_speaker, wifi_fallback, ...
└── Hardware/                  # 3D models, datasheets
```

## Hardware
- **RPi5** 8GB, OV5647 camera, ILI9341 2.2" TFT (SPI0), button GPIO17
- **Audio**: MAX98357A I2S (HifiBerry DAC, card 0) — primary; Bluetooth A2DP (Aceline P450) — optional
- **UPS Module 3S** (Waveshare) + 3×18650 — **integrated** (INA219 @ 0x41 on I2C)
- **MSP2202** screen datasheet in Hardware/

## GPIO Pinout (no conflicts)
| Pin | GPIO | Module | Function |
|-----|------|--------|----------|
| 1 | — | MAX98357A | 3.3V |
| 2,4 | — | UPS | 5V |
| 3 | GPIO2 | UPS | I2C SDA |
| 5 | GPIO3 | UPS | I2C SCL |
| 6,9 | — | UPS / MAX98357A | GND |
| 11 | GPIO17 | Button | Scan (INPUT, pull-up) |
| 12 | GPIO18 | MAX98357A | I2S BCLK |
| 13 | GPIO27 | ILI9341 | LED backlight |
| 18 | GPIO24 | ILI9341 | DC/RS |
| 19 | GPIO10 | ILI9341 | MOSI |
| 22 | GPIO25 | ILI9341 | RESET |
| 23 | GPIO11 | ILI9341 | SCLK |
| 24 | GPIO8 | ILI9341 | CS |
| 35 | GPIO19 | MAX98357A | I2S LRCLK |
| 39 | — | MAX98357A | GND |
| 40 | GPIO21 | MAX98357A | I2S DIN |

## Software Stack
- **Camera**: picamera2 (32 FPS @ 160x120 preview, 640x480 hi-res capture)
- **Display**: ILI9341 SPI0, RGB565, lgpio; **status bar** bottom (lang | IP | WiFi | battery)
- **LLM**: Ollama vision models
- **TTS**: Silero (ru=xenia, en=en_0, es=es_1, zh→en); low-battery voice warn ≤15%
- **I2S**: MAX98357A via `dtoverlay=hifiberry-dac` (card 0). config.txt: `dtparam=audio=off`, `dtoverlay=hifiberry-dac`
- **UPS**: INA219 I2C 0x41 (`modules/ups.py`, `tools/test_ups.py`)
- **Web UI**: :8080, battery badge/panel + `/api/battery`, Wi-Fi in Settings, i18n (ru/en/zh/es)
- **WiFi**: `modules/wifi.py` via `sudo -n nmcli`. Scan list in client mode; **AP mode = manual SSID + password** (no scan button). Connect from AP drops AP, rescans, connects (restores AP on fail). Show/hide password button.
- **WiFi fallback**: `scanner-wifi-fallback.service` — if no known AP → hotspot **Scanner-AP** / `scanner123` (`tools/wifi_fallback.py`)
- **Audio out**: PulseAudio (paplay), fallback aplay plughw:0,0

## Installed Ollama Models
| Model | Size | Speed | Vision | Russian |
|-------|------|-------|--------|---------|
| **qwen3.5:0.8b** | 1.0 GB | ~28s | ✅ | ✅ |
| **qwen2.5vl:3b** | 3.2 GB | ~107s | ✅ | ✅ |

## Key Fixes Applied

### Camera
- picamera2 on system Python 3.13 (no sys.path hack)
- BGR888 → BGR swap (`frame[:, :, ::-1]`), 180° flip
- `LIBCAMERA_LOG_LEVELS=*:ERROR`
- Keyboard scan: `sys.stdin.isatty()`

### GPIO
- lgpio, not RPi.GPIO (RPi5)

### Audio
- PipeWire → PulseAudio; paplay for BT resample
- I2S MAX98357A enabled (2026-10-13); HifiBerry DAC card 0
- TTS: paplay → aplay fallback
- Session audio files: `audio.wav` (not .mp3)

### UPS / Battery
- Wiring: SDA GPIO2, SCL GPIO3, **common GND** (do NOT put Pi GND into 3.3V)
- INA219 responds at **0x41** (also probes 0x40/0x44/0x45)
- `modules/ups.py` + battery icon on display + Web UI panel
- Low-battery TTS warning at ≤15% (repeat 5 min); texts ru/en/es (zh→en audio)
- Test: `python3 tools/test_ups.py [--loop] [--raw]`

### Web UI
- Model selector, SSE logs, auto-refresh scans
- Battery badge in header (click = detailed panel), `/api/battery`
- `/api/scan/<id>/audio` serves `audio.wav` and legacy `audio.mp3`

## Service Management
```bash
sudo systemctl start|stop|restart|status scanner
journalctl -u scanner -f
```

## Tools (manual tests)
| Script | Purpose |
|--------|---------|
| `tools/test_ups.py` | UPS INA219 voltage/current/% |
| `tools/test_i2s.py` | MAX98357A / HifiBerry tone test |
| `tools/test_speaker.py` | Voice samples A/B for speakers |
| `tools/test_button.py` | GPIO17 button |
| `tools/test_display.py` | ILI9341 |
| `tools/test_tts.py` | Silero (note: uses old `tts.model_id` attr — may fail) |

## Known Issues / TODO
- ✅ FPS: picamera2 32 FPS
- ✅ Bluetooth / I2S MAX98357A audio
- ✅ WiFi SkyNet
- ✅ UPS 3S I2C battery monitor + UI + voice warn
- ⏳ 3D model: RPi standoffs after dry-fit
- ⏳ screen_case.obj: clips refinement in Blender

## 3D Models
- `Hardware/scanner_parts/` — screen case, clips, OBJ/STL
- Display: MSP2202 (67.2×40.1mm PCB)

## LLM Prompt (data/settings.json)
```
You are a PDA scanner from the game Subnautica. You analyze objects detected by the scanner camera.

STRICT RULES:
1. ALWAYS start with: НАЙДЕН: [object name] (or FOUND:, ENCONTRADO:, 找到: depending on language)
2. NEVER start with "На изображении" or "On the image" or similar phrases
3. For MAN-MADE objects: state the material (plastic/metal/wood/glass) and its purpose
4. For LIVING things: state the species/class, habitat, and diet
5. Add ONE interesting fact at the end
6. MAXIMUM 3 short sentences total
7. Use the selected language for the entire response
8. Do NOT use brackets [] in the object name
9. Be concise and factual like a real PDA scanner
```
