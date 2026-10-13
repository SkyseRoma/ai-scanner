# Scanner

Subnautica扫描仪外壳中的自主AI设备。从摄像头捕获图像，通过本地LLM分析，并语音播报结果。完全运行在Raspberry Pi 5上，使用电池供电。

## 架构

```
摄像头 (OV5647) → picamera2 → ILI9341 (显示屏, 实时预览)
                     │
                     └─ 按钮 → JPEG → Ollama (qwen3.5:0.8b) → 文本 → BT/I2S (音频)
                                                              └─ 保存到 data/database/<timestamp>/
```

## 全新系统安装

### 1. Raspberry Pi OS Lite (64-bit)

使用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 刷入 Raspberry Pi OS Lite：
- **OS**: Raspberry Pi OS Lite (64-bit) — 无桌面环境
- **SSH**: 启用
- **Wi-Fi**: 如无以太网则配置
- **Hostname**: `scanner`

### 2. 连接

```bash
ssh pi@scanner.local
```

### 3. 基本设置

```bash
sudo apt update && sudo apt upgrade -y
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0
sudo reboot
```

### 4. 安装依赖

```bash
sudo apt install -y python3-pip python3-dev libcamera-dev python3-libcamera \
    rpicam-apps libportaudio2 portaudio19-dev git i2c-tools spi-tools \
    libopenblas-dev liblapack-dev cmake build-essential libcap-dev \
    pulseaudio pulseaudio-module-bluetooth bluetooth bluez libspa-0.2-bluetooth

pip install --break-system-packages picamera2 numpy opencv-python RPi.GPIO \
    rpi-lgpio spidev requests pillow omegaconf pyyaml soundfile
```

### 5. 安装 Ollama 和模型

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:0.8b
ollama pull qwen2.5vl:3b
```

### 6. 克隆仓库

```bash
cd ~ && mkdir -p PROJECTS
git clone https://github.com/SkyseRoma/scanner.git PROJECTS/scanner
```

### 7. 蓝牙音频 (可选)

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

### 8. 自启动服务

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

### 9. 验证

浏览器打开: `http://scanner.local:8080`

## 硬件

| 组件 | 描述 |
|------|------|
| SoC | Raspberry Pi 5 (8GB) |
| 摄像头 | OV5647, 640×480, CSI |
| 显示屏 | MSP2202 ILI9341 TFT 2.2" 320×240, SPI |
| 音频 | MAX98357A I2S, 3W扬声器 / Bluetooth A2DP |
| AI | Ollama + qwen3.5:0.8b / qwen2.5vl:3b (本地CPU) |
| 电源 | UPS Module 3S (Waveshare) + 3×18650 2500mAh |
| 按钮 | 触觉按钮 (扫描触发) |
| 外壳 | 3D打印, Subnautica扫描仪 (`Hardware/`)

## GPIO引脚 (BCM)

所有模块连接到40针接口。**无冲突。**

| 针脚 | GPIO | 模块 | 功能 |
|------|------|------|------|
| 1 | — | MAX98357A | 3.3V (DAC供电) |
| 2 | — | UPS Module | 5V |
| 3 | GPIO2 | UPS Module | I2C SDA (电池监控) |
| 4 | — | UPS Module | 5V (备用) |
| 5 | GPIO3 | UPS Module | I2C SCL |
| 6 | — | UPS Module / MAX98357A | GND |
| 9 | — | UPS Module | GND (备用) |
| 11 | GPIO17 | 按钮 | 扫描 (INPUT, 上拉) |
| 12 | GPIO18 | MAX98357A | I2S BCLK |
| 13 | GPIO27 | ILI9341 | LED背光 |
| 18 | GPIO24 | ILI9341 | DC/RS |
| 19 | GPIO10 | ILI9341 | MOSI (数据) |
| 22 | GPIO25 | ILI9341 | RESET |
| 23 | GPIO11 | ILI9341 | SCLK (时钟) |
| 24 | GPIO8 | ILI9341 | CS (片选) |
| 35 | GPIO19 | MAX98357A | I2S LRCLK |
| 39 | — | MAX98357A | GND |
| 40 | GPIO21 | MAX98357A | I2S DIN |

## 模块

| 文件 | 用途 |
|------|------|
| `main.py` | 主循环: 摄像头 → 显示屏 → 扫描 → LLM → TTS + 电池图标 |
| `modules/camera.py` | Camera类 — picamera2捕获 |
| `modules/disp.py` | Display类 — ILI9341 SPI驱动 |
| `modules/llm.py` | LLM引擎 — Ollama API |
| `modules/tts.py` | TTS类 — Silero语音合成 |
| `modules/ups.py` | UPS类 — Waveshare UPS 3S (INA219 I2C) |
| `modules/web_ui.py` | Web UI: 扫描记录, 聊天, 设置, 日志, 电池 |
| `data/settings.json` | 设置: Ollama地址, 模型, 提示词 |

## LLM后端

**Ollama** + **qwen3.5:0.8b** 模型 (~15秒/响应)。

- API: `http://localhost:11434/api/chat` (原生Ollama)
- 模型首次请求时加载到RAM
- `think: false` — 禁用思考模式以提高速度
- 提示词: Subnautica PDA风格 — 简洁、科学、带物体分类

已测试的替代模型:
| 模型 | 时间 | 多语言 | 大小 |
|------|------|--------|------|
| **qwen3.5:0.8b** | ~15s | ✅ | 1GB |
| **qwen2.5vl:3b** | ~107s | ✅ | 3.2GB |
| gemma2:2b | ~30s | ❌ | 1.6GB |

## 运行

```bash
# SSH连接Raspberry Pi
ssh pi@scanner.local

# 手动启动扫描仪 (调试用)
cd ~/PROJECTS/scanner
python3 main.py
```

浏览器打开: `http://scanner.local:8080`

- 实时摄像头预览
- 按钮或ENTER — 拍摄 + 分析 + 语音
- **Ctrl+C** — 停止

## 服务管理

扫描仪和Ollama作为systemd服务运行，开机自动启动。

```bash
# 状态
sudo systemctl status scanner
sudo systemctl status ollama

# 停止
sudo systemctl stop scanner

# 启动
sudo systemctl start scanner

# 重启
sudo systemctl restart scanner

# 禁用自动启动
sudo systemctl disable scanner

# 启用自动启动
sudo systemctl enable scanner

# 实时日志
journalctl -u scanner -f
```

## 电源

| 组件 | 电压 | 功耗 |
|------|------|------|
| Raspberry Pi 5 | 5V | 3-12W |
| ILI9341显示屏 | 3.3V | ~0.2W |
| MAX98357A音频 | 3.3V | ~0.5W (峰值) |
| OV5647摄像头 | 来自RPi | ~0.5W |

**电源:** UPS Module 3S (Waveshare) + 3×18650 2500mAh
**续航:** ~5小时 (中等负载), ~8小时 (空闲)

## 扫描会话结构

```
data/database/
  └── 2026-09-27_14-30-00/
      ├── shot.jpg       # 摄像头帧
      ├── answer.txt     # LLM文本响应
      └── audio.wav      # 语音响应
```