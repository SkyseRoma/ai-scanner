# Scanner

Автономное AI-устройство в корпусе сканера из Subnautica. Захватывает изображение с камеры, анализирует через локальную LLM и озвучивает результат. Всё работает на Raspberry Pi 5 с автономным питанием от аккумуляторов.

## Архитектура

```
Камера (OV5647) → picamera2 → ILI9341 (дисплей, live-трансляция)
                     │
                     └─ Кнопка → JPEG → Ollama (qwen3.5:0.8b) → текст → BT/I2S (звук)
                                                            └─ сохраняется в data/database/<timestamp>/
```

## Установка на чистую систему

### 1. Raspberry Pi OS Lite (64-bit)

Установите Raspberry Pi OS Lite через [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
- **OS**: Raspberry Pi OS Lite (64-bit) — без рабочего стола
- **SSH**: включить
- **Wi-Fi**: указать если нет Ethernet
- **Hostname**: `scanner`

### 2. Подключение

```bash
ssh pi@scanner.local
```

### 3. Базовая настройка

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Включение SPI и I2C
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# Перезагрузка
sudo reboot
```

### 4. Установка зависимостей

```bash
# Системные пакеты
sudo apt install -y python3-pip python3-dev libcamera-dev python3-libcamera \
    rpicam-apps libportaudio2 portaudio19-dev git i2c-tools spi-tools \
    libopenblas-dev liblapack-dev cmake build-essential libcap-dev \
    pulseaudio pulseaudio-module-bluetooth bluetooth bluez libspa-0.2-bluetooth

# Python пакеты
pip install --break-system-packages picamera2 numpy opencv-python RPi.GPIO \
    rpi-lgpio spidev requests pillow omegaconf pyyaml soundfile
```

### 5. Установка Ollama и моделей

```bash
# Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Модели
ollama pull qwen3.5:0.8b      # быстрая (1GB)
ollama pull qwen2.5vl:3b      # умная (3.2GB)
```

### 6. Клонирование проекта

```bash
cd ~
mkdir -p PROJECTS
git clone https://github.com/SkyseRoma/scanner.git PROJECTS/scanner
```

### 7. Настройка Bluetooth аудио (опционально)

```bash
# В rc.local для автоподключения
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

### 8. Автозапуск

```bash
# Ollama сервис (создаётся автоматически при установке)
sudo systemctl enable ollama

# Scanner сервис
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

### 9. Проверка

Откройте в браузере: `http://scanner.local:8080`

## Железо

| Компонент | Описание |
|-----------|----------|
| SoC | Raspberry Pi 5 (8GB) |
| Камера | OV5647, 640×480, CSI-подключение |
| Дисплей | MSP2202 ILI9341 TFT 2.2" 320×240, SPI |
| Аудио | MAX98357A I2S, 3W на динамик |
| AI | Ollama + qwen3.5:0.8b (локально на CPU) |
| Питание | UPS Module 3S (Waveshare) + 3×18650 2500mAh |
| Кнопка | Тактильная кнопка (сканирование) |
| Корпус | 3D-печать, сканер из Subnautica (`Hardware/subnuatica_scanner.3mf`) |

## Распиновка GPIO (BCM)

Все модули подключены к одному 40-пиновому разъёму. **Конфликтов нет.**

| Пин | GPIO | Модуль | Функция |
|-----|------|--------|---------|
| 1 | — | MAX98357A | 3.3V (питание DAC) |
| 2 | — | UPS Module | 5V |
| 3 | GPIO2 | UPS Module | I2C SDA (мониторинг заряда) |
| 4 | — | UPS Module | 5V (дубль) |
| 5 | GPIO3 | UPS Module | I2C SCL |
| 6 | — | UPS Module / MAX98357A | GND |
| 9 | — | UPS Module | GND (дубль) |
| 11 | GPIO17 | Кнопка | Сканирование (INPUT, pull-up) |
| 12 | GPIO18 | MAX98357A | I2S BCLK |
| 13 | GPIO27 | ILI9341 | LED подсветка |
| 18 | GPIO24 | ILI9341 | DC/RS |
| 19 | GPIO10 | ILI9341 | MOSI (данные) |
| 22 | GPIO25 | ILI9341 | RESET |
| 23 | GPIO11 | ILI9341 | SCLK (тактовый) |
| 24 | GPIO8 | ILI9341 | CS (chip select) |
| 35 | GPIO19 | MAX98357A | I2S LRCLK |
| 39 | — | MAX98357A | GND |
| 40 | GPIO21 | MAX98357A | I2S DIN |

**Итого занято:** GPIO 2, 3, 8, 10, 11, 17, 18, 19, 21, 24, 25, 27 (12 пинов)
**Свободно:** GPIO 4, 5, 6, 9, 12, 13, 14, 15, 16, 20, 23, 26

### Дисплей MSP2202 (ILI9341, SPI)

Дисплей питается от **3.3V** (не 5V!). Подсветка через GPIO27 (PWM).

| Пин экрана | GPIO RPi | Пин RPi |
|------------|----------|---------|
| VCC | — | 3.3V (пин 1) |
| GND | — | GND (пин 6) |
| CS | GPIO8 | пин 24 |
| RESET | GPIO25 | пин 22 |
| DC/RS | GPIO24 | пин 18 |
| MOSI | GPIO10 | пин 19 |
| SCLK | GPIO11 | пин 23 |
| LED | GPIO27 | пин 13 |

### Аудио MAX98357A (I2S)

| Пин модуля | GPIO RPi | Пин RPi |
|------------|----------|---------|
| VIN | — | 3.3V (пин 1) |
| GND | — | GND (пин 39) |
| DIN | GPIO21 | пин 40 |
| BCLK | GPIO18 | пин 12 |
| LRC | GPIO19 | пин 35 |
| Speaker+ | — | Динамик + |
| Speaker- | — | Динамик - |

### UPS Module 3S (питание + I2C)

| Пин модуля | GPIO RPi | Пин RPi |
|------------|----------|---------|
| 5V | — | пин 2, 4 |
| GND | — | пин 6, 9 |
| SDA | GPIO2 | пин 3 |
| SCL | GPIO3 | пин 5 |

### Кнопка сканирования

| Контакт | Подключение |
|---------|-------------|
| Один | GPIO17 (пин 11) |
| Другой | GND (пин 14) |

Pull-up внутренний: `GPIO.PUD_UP`. Нажатие = LOW.

## Модули

| Файл | Назначение |
|------|------------|
| `main.py` | Главный цикл: камера → дисплей → снимок → LLM → TTS |
| `scanner_web.py` | Web UI: MJPEG стрим + кнопка сканирования |
| `camera_stream.py` | MJPEG stream server (только видео) |
| `camera_test.py` | Тест захвата одного кадра |
| `modules/camera.py` | Класс `Camera` — захват через rpicam-still |
| `modules/disp.py` | Класс `PiCameraDisplay` — трансляция на ILI9341 через SPI |
| `modules/llm.py` | Класс `LLM_engine` — запросы к Ollama (нативный API) |
| `modules/tts.py` | Класс `TTS` — генерация речи (Silero `v4_ru`, голос `aidar`) |
| `modules/settings.json` | Настройки: адрес Ollama, модель, промпт |
| `modules/database/` | Сессии: `shot.jpg`, `answer.txt`, `audio.mp3` |

## LLM-бэкенд

**Ollama** с моделью **qwen3.5:0.8b** (~15 сек на ответ, русский язык).

- API: `http://localhost:11434/api/chat` (нативный Ollama)
- Модель загружается в RAM при первом запросе
- `think: false` — отключает режим "мышления" для скорости
- Промпт: стиль PDA из Subnautica — сухой, научный, с классификацией объекта

Альтернативы (протестированы):
| Модель | Время | Русский | Размер |
|--------|-------|---------|--------|
| **qwen3.5:0.8b** | ~15 сек | ✅ | 1GB |
| minicpm-v4.6 | ~12 сек | ❌ | 1.6GB |
| gemma3:4b | ~90 сек | ✅ | 3.3GB |
| qwen2.5vl:3b | ~140 сек | ✅ | 3.2GB |

## Запуск

```bash
# SSH на Raspberry Pi 5
ssh airpi2@192.168.1.21

# Активировать окружение
conda activate scanner

# Запустить Ollama (если не запущен)
OLLAMA_MAX_LOADED_MODELS=1 nohup ollama serve &

# Запустить web UI
cd PROJECTS/scanner
python3 scanner_web.py
```

Открыть в браузере: `http://192.168.1.21:9090`

- Видео обновляется в реальном времени
- Кнопка **«СКАНИРОВАТЬ»** — захват + анализ + озвучка
- **Ctrl+C** — остановка

## Питание

| Компонент | Напряжение | Потребление |
|-----------|-----------|-------------|
| Raspberry Pi 5 | 5V | 3-12W |
| ILI9341 дисплей | 3.3V | ~0.2W |
| MAX98357A аудио | 3.3V | ~0.5W (пик) |
| OV5647 камера | от RPi | ~0.5W |

**Источник:** UPS Module 3S (Waveshare) + 3×18650 2500mAh
**Время работы:** ~5 часов (средняя нагрузка), ~8 часов (холостой)

## Зависимости

```
conda activate scanner
pip install opencv-python-headless numpy Pillow soundfile torch requests RPi.GPIO spidev
```

## Структура сессии (database)

```
modules/database/
  └── 2026-06-22_21-30-53/
      ├── shot.jpg       # кадр с камеры
      ├── answer.txt     # текстовый ответ LLM
      └── audio.mp3      # озвученный ответ
```

## Управление сервисами

Сканер и Ollama работают как systemd-сервисы и запускаются автоматически при загрузке.

```bash
# Статус
sudo systemctl status scanner
sudo systemctl status ollama

# Остановить
sudo systemctl stop scanner

# Запустить
sudo systemctl start scanner

# Перезапустить
sudo systemctl restart scanner

# Отключить автозапуск
sudo systemctl disable scanner

# Включить автозапуск
sudo systemctl enable scanner

# Логи в реальном времени
journalctl -u scanner -f
```

### Ручной запуск (для отладки)

```bash
cd ~/PROJECTS/scanner
python3 main.py
```
