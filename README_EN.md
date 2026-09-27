# Scanner

Autonomous AI device in a Subnautica scanner case. Captures images from a camera, analyzes them with a local LLM, and speaks the result. Runs entirely on Raspberry Pi 5 with battery power.

## Architecture

```
Camera (OV5647) → picamera2 → ILI9341 (display, live preview)
                     │
                     └─ Button → JPEG → Ollama (qwen3.5:0.8b) → text → MAX98357A (audio)
                                                            └─ saved to data/database/<timestamp>/
```

## Hardware

| Component | Description |
|-----------|-------------|
| SoC | Raspberry Pi 5 (8GB) |
| Camera | OV5647, 640×480, CSI |
| Display | MSP2202 ILI9341 TFT 2.2" 320×240, SPI |
| Audio | MAX98357A I2S, 3W speaker / Bluetooth A2DP |
| AI | Ollama + qwen3.5:0.8b / qwen2.5vl:3b (local CPU) |
| Power | UPS Module 3S (Waveshare) + 3×18650 2500mAh |
| Button | Tactile button (scan trigger) |
| Case | 3D printed, Subnautica scanner (`Hardware/`) |

## GPIO Pinout (BCM)

All modules connected to single 40-pin header. **No conflicts.**

| Pin | GPIO | Module | Function |
|-----|------|--------|----------|
| 1 | — | MAX98357A | 3.3V (DAC power) |
| 2 | — | UPS Module | 5V |
| 3 | GPIO2 | UPS Module | I2C SDA (battery monitor) |
| 4 | — | UPS Module | 5V (backup) |
| 5 | GPIO3 | UPS Module | I2C SCL |
| 6 | — | UPS Module / MAX98357A | GND |
| 9 | — | UPS Module | GND (backup) |
| 11 | GPIO17 | Button | Scan (INPUT, pull-up) |
| 12 | GPIO18 | MAX98357A | I2S BCLK |
| 13 | GPIO27 | ILI9341 | LED backlight |
| 18 | GPIO24 | ILI9341 | DC/RS |
| 19 | GPIO10 | ILI9341 | MOSI (data) |
| 22 | GPIO25 | ILI9341 | RESET |
| 23 | GPIO11 | ILI9341 | SCLK (clock) |
| 24 | GPIO8 | ILI9341 | CS (chip select) |
| 35 | GPIO19 | MAX98357A | I2S LRCLK |
| 39 | — | MAX98357A | GND |
| 40 | GPIO21 | MAX98357A | I2S DIN |

## Modules

| File | Purpose |
|------|---------|
| `main.py` | Main loop: camera → display → scan → LLM → TTS |
| `modules/camera.py` | Camera class — picamera2 capture |
| `modules/disp.py` | Display class — ILI9341 via SPI |
| `modules/llm.py` | LLM engine — Ollama API |
| `modules/tts.py` | TTS class — Silero text-to-speech |
| `modules/web_ui.py` | Web UI: scans, chat, settings, logs |
| `data/settings.json` | Settings: Ollama address, model, prompt |

## LLM Backend

**Ollama** with **qwen3.5:0.8b** model (~15s per response).

- API: `http://localhost:11434/api/chat` (native Ollama)
- Model loads into RAM on first request
- `think: false` — disables thinking mode for speed
- Prompt: Subnautica PDA style — dry, scientific, with object classification

Tested alternatives:
| Model | Time | Multilingual | Size |
|-------|------|-------------|------|
| **qwen3.5:0.8b** | ~15s | ✅ | 1GB |
| **qwen2.5vl:3b** | ~107s | ✅ | 3.2GB |
| gemma2:2b | ~30s | ❌ | 1.6GB |

## Running

```bash
# SSH into Raspberry Pi
ssh pi@scanner.local

# Start scanner manually (for debugging)
cd ~/PROJECTS/scanner
python3 main.py
```

Open in browser: `http://scanner.local:8080`

- Live camera preview
- Button or ENTER — capture + analyze + speak
- **Ctrl+C** — stop

## Service Management

Scanner and Ollama run as systemd services, starting automatically on boot.

```bash
# Status
sudo systemctl status scanner
sudo systemctl status ollama

# Stop
sudo systemctl stop scanner

# Start
sudo systemctl start scanner

# Restart
sudo systemctl restart scanner

# Disable autostart
sudo systemctl disable scanner

# Enable autostart
sudo systemctl enable scanner

# Live logs
journalctl -u scanner -f
```

## Power

| Component | Voltage | Consumption |
|-----------|---------|-------------|
| Raspberry Pi 5 | 5V | 3-12W |
| ILI9341 display | 3.3V | ~0.2W |
| MAX98357A audio | 3.3V | ~0.5W (peak) |
| OV5647 camera | from RPi | ~0.5W |

**Source:** UPS Module 3S (Waveshare) + 3×18650 2500mAh
**Battery life:** ~5 hours (medium load), ~8 hours (idle)

## Scan Session Structure

```
data/database/
  └── 2026-09-27_14-30-00/
      ├── shot.jpg       # camera frame
      ├── answer.txt     # LLM text response
      └── audio.mp3      # spoken response
```