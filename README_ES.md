# Scanner

Dispositivo AI autónomo en una carcasa de escáner de Subnautica. Captura imágenes de la cámara, las analiza con un LLM local y verbaliza el resultado. Funciona completamente en Raspberry Pi 5 con batería.

## Arquitectura

```
Cámara (OV5647) → picamera2 → ILI9341 (pantalla, vista previa)
                     │
                     └─ Botón → JPEG → Ollama (qwen3.5:0.8b) → texto → BT/I2S (audio)
                                                              └─ guardado en data/database/<timestamp>/
```

## Instalación en Sistema Limpio

### 1. Raspberry Pi OS Lite (64-bit)

Instale Raspberry Pi OS Lite con [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
- **OS**: Raspberry Pi OS Lite (64-bit) — sin escritorio
- **SSH**: habilitar
- **Wi-Fi**: configurar si no hay Ethernet
- **Hostname**: `scanner`

### 2. Conectar

```bash
ssh pi@scanner.local
```

### 3. Configuración Básica

```bash
sudo apt update && sudo apt upgrade -y
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
sudo reboot
```

### 4. Instalar Dependencias

```bash
sudo apt install -y python3-pip python3-dev libcamera-dev python3-libcamera \
    rpicam-apps libportaudio2 portaudio19-dev git i2c-tools spi-tools \
    libopenblas-dev liblapack-dev cmake build-essential libcap-dev \
    pulseaudio pulseaudio-module-bluetooth bluetooth bluez libspa-0.2-bluetooth

pip install --break-system-packages picamera2 numpy opencv-python RPi.GPIO \
    rpi-lgpio spidev requests pillow omegaconf pyyaml soundfile
```

### 5. Instalar Ollama y Modelos

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:0.8b
ollama pull qwen2.5vl:3b
```

### 6. Clonar Repositorio

```bash
cd ~ && mkdir -p PROJECTS
git clone https://github.com/SkyseRoma/scanner.git PROJECTS/scanner
```

### 7. Audio Bluetooth (opcional)

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

### 8. Servicios de Autoarranque

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

### 9. Verificar

Abrir en navegador: `http://scanner.local:8080`

## Hardware

| Componente | Descripción |
|------------|-------------|
| SoC | Raspberry Pi 5 (8GB) |
| Cámara | OV5647, 640×480, CSI |
| Pantalla | MSP2202 ILI9341 TFT 2.2" 320×240, SPI |
| Audio | MAX98357A I2S, altavoz 3W / Bluetooth A2DP |
| AI | Ollama + qwen3.5:0.8b / qwen2.5vl:3b (CPU local) |
| Energía | UPS Module 3S (Waveshare) + 3×18650 2500mAh |
| Botón | Botón táctil (escaneo) |
| Carcasa | Impresión 3D, escáner de Subnautica (`Hardware/`) |

## GPIO Pinout (BCM)

Todos los módulos conectados al header de 40 pines. **Sin conflictos.**

| Pin | GPIO | Módulo | Función |
|-----|------|--------|---------|
| 1 | — | MAX98357A | 3.3V (alimentación DAC) |
| 2 | — | UPS Module | 5V |
| 3 | GPIO2 | UPS Module | I2C SDA (monitoreo batería) |
| 4 | — | UPS Module | 5V (respaldo) |
| 5 | GPIO3 | UPS Module | I2C SCL |
| 6 | — | UPS Module / MAX98357A | GND |
| 9 | — | UPS Module | GND (respaldo) |
| 11 | GPIO17 | Botón | Escaneo (INPUT, pull-up) |
| 12 | GPIO18 | MAX98357A | I2S BCLK |
| 13 | GPIO27 | ILI9341 | LED retroiluminación |
| 18 | GPIO24 | ILI9341 | DC/RS |
| 19 | GPIO10 | ILI9341 | MOSI (datos) |
| 22 | GPIO25 | ILI9341 | RESET |
| 23 | GPIO11 | ILI9341 | SCLK (reloj) |
| 24 | GPIO8 | ILI9341 | CS (chip select) |
| 35 | GPIO19 | MAX98357A | I2S LRCLK |
| 39 | — | MAX98357A | GND |
| 40 | GPIO21 | MAX98357A | I2S DIN |

## Módulos

| Archivo | Propósito |
|---------|-----------|
| `main.py` | Bucle principal: cámara → pantalla → escaneo → LLM → TTS + icono de batería |
| `modules/camera.py` | Clase Camera — captura con picamera2 |
| `modules/disp.py` | Clase Display — ILI9341 vía SPI |
| `modules/llm.py` | Motor LLM — API de Ollama |
| `modules/tts.py` | Clase TTS — Silero texto-a-voz |
| `modules/ups.py` | Clase UPS — Waveshare UPS 3S (INA219 I2C) |
| `modules/web_ui.py` | Web UI: escaneos, chat, ajustes, logs, batería |
| `data/settings.json` | Ajustes: dirección Ollama, modelo, prompt |

## Backend LLM

**Ollama** con modelo **qwen3.5:0.8b** (~15s por respuesta).

- API: `http://localhost:11434/api/chat` (Ollama nativo)
- El modelo se carga en RAM en la primera solicitud
- `think: false` — desactiva el modo de pensamiento para velocidad
- Prompt: estilo PDA de Subnautica — seco, científico, con clasificación

Alternativas probadas:
| Modelo | Tiempo | Multilingüe | Tamaño |
|--------|--------|-------------|--------|
| **qwen3.5:0.8b** | ~15s | ✅ | 1GB |
| **qwen2.5vl:3b** | ~107s | ✅ | 3.2GB |
| gemma2:2b | ~30s | ❌ | 1.6GB |

## Ejecución

```bash
# SSH a Raspberry Pi
ssh pi@scanner.local

# Iniciar escáner manualmente (para depuración)
cd ~/PROJECTS/scanner
python3 main.py
```

Abrir en navegador: `http://scanner.local:8080`

- Vista previa de cámara en vivo
- Botón o ENTER — capturar + analizar + hablar
- **Ctrl+C** — detener

## Gestión de Servicios

El escáner y Ollama se ejecutan como servicios systemd, iniciándose automáticamente al arrancar.

```bash
# Estado
sudo systemctl status scanner
sudo systemctl status ollama

# Detener
sudo systemctl stop scanner

# Iniciar
sudo systemctl start scanner

# Reiniciar
sudo systemctl restart scanner

# Desactivar inicio automático
sudo systemctl disable scanner

# Activar inicio automático
sudo systemctl enable scanner

# Logs en tiempo real
journalctl -u scanner -f
```

## Energía

| Componente | Voltaje | Consumo |
|------------|---------|---------|
| Raspberry Pi 5 | 5V | 3-12W |
| Pantalla ILI9341 | 3.3V | ~0.2W |
| Audio MAX98357A | 3.3V | ~0.5W (pico) |
| Cámara OV5647 | desde RPi | ~0.5W |

**Fuente:** UPS Module 3S (Waveshare) + 3×18650 2500mAh
**Duración batería:** ~5 horas (carga media), ~8 horas (inactivo)

## Estructura de Sesión de Escaneo

```
data/database/
  └── 2026-09-27_14-30-00/
      ├── shot.jpg       # imagen de cámara
      ├── answer.txt     # respuesta de texto LLM
      └── audio.wav      # respuesta hablada
```