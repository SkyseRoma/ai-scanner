# Scanner

Autonomous AI device in a Subnautica scanner case. Captures images from a camera, analyzes them with a local LLM, and speaks the result. Runs entirely on Raspberry Pi 5 with battery power.

## Architecture

```
Camera (OV5647) → picamera2 → ILI9341 (display, live preview)
                     │
                     └─ Button → JPEG → Ollama (qwen3.5:0.8b) → text → BT/I2S (audio)
                                                            └─ saved to data/database/<timestamp>/
```

## Installation on Fresh System

### 1. Raspberry Pi OS Lite (64-bit)

Flash Raspberry Pi OS Lite using [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
- **OS**: Raspberry Pi OS Lite (64-bit) — no desktop
- **SSH**: enable
- **Wi-Fi**: configure if no Ethernet
- **Hostname**: `scanner`

### 2. Connect

```bash
ssh pi@scanner.local
```

### 3. Basic Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
sudo reboot
```

### 4. Install Dependencies

```bash
# System packages
sudo apt install -y python3-pip python3-dev libcamera-dev python3-libcamera \
    rpicam-apps libportaudio2 portaudio19-dev git i2c-tools spi-tools \
    libopenblas-dev liblapack-dev cmake build-essential libcap-dev \
    pulseaudio pulseaudio-module-bluetooth bluetooth bluez libspa-0.2-bluetooth

# Python packages
pip install --break-system-packages picamera2 numpy opencv-python RPi.GPIO \
    rpi-lgpio spidev requests pillow omegaconf pyyaml soundfile
```

### 5. Install Ollama and Models

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:0.8b
ollama pull qwen2.5vl:3b
```

### 6. Clone Repository

```bash
cd ~ && mkdir -p PROJECTS
git clone https://github.com/SkyseRoma/scanner.git PROJECTS/scanner
```

### 7. Bluetooth Audio (optional)

```bash
sudo tee /etc/rc.local << 'EOF'
#!/bin/bash
pkill -9 -f pipewire 2>/dev/null
pkill -9 -f wireplumber 2>/dev/null
pulseaudio --system --daemonize --disallow-exit
sleep 3
echo -e 'connect XX:XX:XX:XX:XX:XX\nquit' | bluetoothctl
sleep 2
pactl set-default-sink bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink 2>/dev/null
exit 0
EOF
sudo chmod +x /etc/rc.local
```

### 8. Autostart Services

```bash
sudo systemctl enable ollama

sudo tee /etc/systemd/system/scanner.service << 'EOF'
[Unit]
Description=Subnautica Scanner
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/PROJECTS/scanner
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable scanner
sudo systemctl start scanner
```

### 9. Verify

Open in browser: `http://scanner.local:8080`

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
| `main.py` | Main loop: camera → display → scan → LLM → TTS + battery icon |
| `modules/camera.py` | Camera class — picamera2 capture |
| `modules/disp.py` | Display class — ILI9341 via SPI |
| `modules/llm.py` | LLM engine — Ollama API |
| `modules/tts.py` | TTS class — Silero text-to-speech |
| `modules/ups.py` | UPS class — Waveshare UPS 3S (INA219 I2C) |
| `modules/web_ui.py` | Web UI: scans, chat, settings, logs, battery |
| `data/settings.json` | Settings: Ollama address, model, prompt |

Tests in `tools/`: `test_ups.py`, `test_i2s.py`, `test_speaker.py`, `test_button.py`, `test_display.py`.

## Battery (UPS Module 3S)

- **INA219** on I2C (address **0x41**): SDA=GPIO2 (pin 3), SCL=GPIO3 (pin 5), common GND
- Battery icon on the ILI9341 display (bottom-right)
- Web UI badge + detailed panel, API `GET /api/battery`
- Voice warning at **≤ 15%** charge (ru/en/es; zh uses English audio)
- Test: `python3 tools/test_ups.py`

**Important:** connect Raspberry Pi GND to UPS **GND**, not 3.3V.

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
      └── audio.wav      # spoken response
```