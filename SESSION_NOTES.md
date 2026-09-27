# Scanner Project — Session Context

## RPi5 Connection (NEW — clean install 2026-09-27)
- **OS**: Raspberry Pi OS Lite (Debian Trixie, aarch64, no desktop)
- **Hostname**: `scanner` → `ssh pi@scanner.local`
- **SSH key**: `~/.ssh/id_ed25519` (ed25519, passwordless)
- **IP (WiFi)**: 192.168.1.21
- **IP (Ethernet)**: 192.168.1.6
- **sudo**: NOPASSWD configured (`/etc/sudoers.d/010_pi-nopasswd`)
- **Project**: `/home/pi/PROJECTS/scanner/`
- **Python**: 3.13.5 (system, no conda)
- **Run manually**: `python3 main.py`
- **Run as service**: `sudo systemctl start scanner`

## Project Structure
```
scanner/
├── main.py                    # main loop: camera → display → scan → LLM → TTS
├── run.sh                     # launcher
├── README.md                  # Russian
├── README_EN.md               # English
├── README_ES.md               # Spanish
├── README_ZH.md               # Chinese
├── .gitignore
├── modules/
│   ├── camera.py              # picamera2, BGR888→BGR swap, 180° flip
│   ├── disp.py                # ILI9341 via SPI0, lgpio (not RPi.GPIO)
│   ├── llm.py                 # Ollama API /api/chat, dynamic model/language
│   ├── tts.py                 # Silero TTS, paplay output, error recovery
│   ├── web_ui.py              # Web UI: scans, chat, settings, logs (SSE)
│   └── __init__.py
├── data/
│   ├── settings.json          # model, prompt, language, IP/port
│   └── database/              # scan sessions (shot.jpg, answer.txt, audio.mp3)
├── tools/                     # test scripts
└── Hardware/                  # 3D models, datasheets
```

## Hardware
- **RPi5** 8GB, OV5647 camera, ILI9341 2.2" TFT (SPI0), button GPIO17
- **Audio**: Bluetooth A2DP speaker (Aceline P450) — currently; MAX98357A I2S — pending delivery
- **UPS Module 3S** (Waveshare) + 3×18650 — ordered
- **MSP2202** screen datasheet in Hardware/

## GPIO Pinout (no conflicts)
| Pin | GPIO | Module | Function |
|-----|------|--------|----------|
| 1 | — | MAX98357A | 3.3V |
| 2,4 | — | UPS | 5V |
| 3 | GPIO2 | UPS | I2C SDA |
| 5 | GPIO3 | UPS | I2C SCL |
| 6,9 | — | UPS | GND |
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
- **Display**: ILI9341 via SPI0, RGB565, partial window updates, lgpio (NOT RPi.GPIO)
- **LLM**: Ollama with vision models (see below)
- **TTS**: Silero TTS (ru=xenia, en=en_0, es=es_1, zh→en fallback), output via paplay
- **Audio**: PulseAudio system mode (NOT PipeWire), Bluetooth A2DP
- **Web UI**: port 8080, scans/chat/settings/logs (SSE), i18n (ru/en/zh/es)

## Installed Ollama Models
| Model | Size | Speed | Vision | Russian |
|-------|------|-------|--------|---------|
| **qwen3.5:0.8b** | 1.0 GB | ~28s | ✅ | ✅ |
| **qwen2.5vl:3b** | 3.2 GB | ~107s | ✅ | ✅ |

## Key Fixes Applied (this session)

### Camera
- **picamera2 on system Python 3.13**: libcamera C++ module available natively (no sys.path hack needed)
- **BGR888 → BGR swap**: picamera2 BGR888 actually gives RGB, need `frame[:, :, ::-1]`
- **Image flip**: 180° in camera.py `capture_array()`
- **LIBCAMERA_LOG_LEVELS=*:ERROR**: suppress C++ log spam
- **Keyboard scan fix**: `sys.stdin.isatty()` check prevents constant scanning in service mode

### GPIO
- **lgpio instead of RPi.GPIO**: RPi.GPIO doesn't work on RPi5 (SOC peripheral base address error)
- lgpio: `gpiochip_open(0)`, `gpio_claim_output()`, `gpio_write()`

### Audio
- **PipeWire → PulseAudio**: PipeWire Bluetooth A2DP doesn't work; PulseAudio system mode works
- **aplay → paplay**: `paplay` properly resamples for Bluetooth (48kHz mono → 44.1kHz stereo)
- **I2S config**: commented out in `/boot/firmware/config.txt` (waiting for MAX98357A delivery)
- **Bluetooth autoconnect**: configured in `/etc/rc.local`

### LLM
- **Dynamic model update**: `gpt.model` and `gpt.prompt` refresh from settings.json before each scan
- **Language injection**: system prompt appends "Respond in {language}" dynamically
- **Prompt**: detailed PDA scanner rules with format requirements

### TTS
- **Error recovery**: 3 attempts with progressive text truncation on failure
- **trust_repo=True**: required for torch.hub.load with newer torch versions
- **Text truncation**: max 500 chars before TTS to avoid Silero kernel size error

### Web UI
- **Model selector**: dropdown populated from `/api/models` (Ollama API)
- **Log panel**: SSE (Server-Sent Events) real-time log viewer
- **Auto-refresh**: scan list updates every 5 seconds
- **Console logging**: language/model changes printed to terminal

## Service Management
```bash
# Scanner
sudo systemctl start scanner
sudo systemctl stop scanner
sudo systemctl restart scanner
sudo systemctl status scanner
journalctl -u scanner -f

# Ollama
sudo systemctl status ollama
sudo systemctl restart ollama
```

## Audio Setup (Bluetooth)
```bash
# Pair speaker (one-time)
bluetoothctl
  power on
  scan on
  pair XX:XX:XX:XX:XX:XX
  trust XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  quit

# Set as default sink
pactl set-default-sink bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink
```

## Known Issues / TODO
- ✅ FPS: picamera2 gives 32 FPS (was 3-5 with rpicam-still)
- ✅ Bluetooth audio: works via PulseAudio system mode
- ⏳ MAX98357A I2S audio: waiting for delivery
- ⏳ Battery (UPS Module 3S): not yet integrated
- ⏳ 3D model: standoffs for RPi need adjustment after physical dry-fit
- ⏳ screen_case.obj: clips/latches designed, need refinement in Blender

## 3D Models
- `Hardware/scanner_parts/screen_case.obj` — screen case (2 parts: back + front)
- `Hardware/scanner_parts/screen_case_clips.obj` — with snap-fit clips added
- `Hardware/scanner_parts/` — OBJ/STL files for Blender/printing
- Display: MSP2202 (67.2×40.1mm PCB, 45.12×33.84mm active)

## LLM Prompt (in settings.json)
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