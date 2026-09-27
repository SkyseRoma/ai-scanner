"""
ILI9341 display test on Raspberry Pi 5.
Run: python3 test_display.py
"""

import time
import spidev
import numpy as np
import RPi.GPIO as GPIO

# ── Pins (BCM) ─────────────────────────────────────────────────────────
DC_PIN  = 24
RST_PIN = 25
WIDTH   = 320
HEIGHT  = 240

# ── Initialization ─────────────────────────────────────────────────────
print("Initializing GPIO...")
GPIO.setmode(GPIO.BCM)
GPIO.setup(DC_PIN, GPIO.OUT)
GPIO.setup(RST_PIN, GPIO.OUT)

print("Initializing SPI...")
spi = spidev.SpiDev()
spi.open(0, 0)  # SPI0
spi.max_speed_hz = 40000000
spi.mode = 0b00


def send_cmd(cmd):
    GPIO.output(DC_PIN, GPIO.LOW)
    spi.writebytes([cmd])


def send_data(data):
    GPIO.output(DC_PIN, GPIO.HIGH)
    if isinstance(data, list):
        spi.writebytes(data)
    else:
        spi.writebytes2(data)


def init_display():
    """Hardware reset and ILI9341 initialization."""
    print("Resetting display...")
    GPIO.output(RST_PIN, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST_PIN, GPIO.HIGH)
    time.sleep(0.1)

    send_cmd(0x01)  # Software Reset
    time.sleep(0.1)
    send_cmd(0x28)  # Display OFF

    send_cmd(0x36)  # MADCTL — orientation
    send_data([0x28])  # landscape, RGB

    send_cmd(0x3A)  # Pixel Format
    send_data([0x55])  # 16-bit RGB565

    send_cmd(0x11)  # Exit Sleep
    time.sleep(0.1)
    send_cmd(0x29)  # Display ON
    time.sleep(0.05)
    print("Display initialized.")


def set_window(x0=0, y0=0, x1=WIDTH-1, y1=HEIGHT-1):
    send_cmd(0x2A)
    send_data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
    send_cmd(0x2B)
    send_data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
    send_cmd(0x2C)


def fill_color(r, g, b):
    """Fill screen with RGB888 -> RGB565 color."""
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    pixel = (r5 << 11) | (g6 << 5) | b5
    hi = (pixel >> 8) & 0xFF
    lo = pixel & 0xFF
    set_window()
    buf = bytes([hi, lo] * WIDTH * HEIGHT)
    send_data(buf)


def draw_gradient():
    """Vertical gradient (red -> blue)."""
    set_window()
    buf = bytearray()
    for y in range(HEIGHT):
        r = int(255 * (1 - y / HEIGHT))
        b = int(255 * (y / HEIGHT))
        r5 = (r >> 3) & 0x1F
        g6 = 0
        b5 = (b >> 3) & 0x1F
        pixel = (r5 << 11) | (g6 << 5) | b5
        hi = (pixel >> 8) & 0xFF
        lo = pixel & 0xFF
        buf.extend([hi, lo] * WIDTH)
    send_data(bytes(buf))


def draw_grid(step=40):
    """White grid on black background."""
    fill_color(0, 0, 0)
    # Horizontal lines
    for y in range(0, HEIGHT, step):
        set_window(0, y, WIDTH - 1, y)
        send_data(b'\xff\xff' * WIDTH)
    # Vertical lines
    for x in range(0, WIDTH, step):
        set_window(x, 0, x, HEIGHT - 1)
        send_data(b'\xff\xff' * HEIGHT)


def draw_border(color=(0, 255, 0)):
    """Border around the perimeter."""
    r5 = (color[0] >> 3) & 0x1F
    g6 = (color[1] >> 2) & 0x3F
    b5 = (color[2] >> 3) & 0x1F
    pixel = (r5 << 11) | (g6 << 5) | b5
    hi = (pixel >> 8) & 0xFF
    lo = pixel & 0xFF
    px = bytes([hi, lo])
    w = 3  # border thickness

    # Top
    set_window(0, 0, WIDTH - 1, w - 1)
    send_data(px * WIDTH * w)
    # Bottom
    set_window(0, HEIGHT - w, WIDTH - 1, HEIGHT - 1)
    send_data(px * WIDTH * w)
    # Left
    set_window(0, 0, w - 1, HEIGHT - 1)
    send_data(px * w * HEIGHT)
    # Right
    set_window(WIDTH - w, 0, WIDTH - 1, HEIGHT - 1)
    send_data(px * w * HEIGHT)


def cleanup():
    spi.close()
    GPIO.cleanup()
    print("Cleanup complete.")


# ── Tests ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        init_display()

        print("Test 1: red screen")
        fill_color(255, 0, 0)
        time.sleep(1)

        print("Test 2: green screen")
        fill_color(0, 255, 0)
        time.sleep(1)

        print("Test 3: blue screen")
        fill_color(0, 0, 255)
        time.sleep(1)

        print("Test 4: white screen")
        fill_color(255, 255, 255)
        time.sleep(1)

        print("Test 5: black screen")
        fill_color(0, 0, 0)
        time.sleep(0.5)

        print("Test 6: gradient")
        draw_gradient()
        time.sleep(2)

        print("Test 7: grid")
        draw_grid()
        time.sleep(2)

        print("Test 8: border on black")
        fill_color(0, 0, 0)
        draw_border((0, 255, 0))
        time.sleep(2)

        print("Test 9: capture camera frame to display")
        import subprocess
        subprocess.run([
            "rpicam-still", "--width", "320", "--height", "240",
            "--immediate", "--nopreview", "-o", "/tmp/display_test.jpg"
        ], capture_output=True, timeout=10)

        import cv2
        frame = cv2.imread("/tmp/display_test.jpg")
        if frame is not None:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (WIDTH, HEIGHT))
            # Convert to RGB565 (R=bits 15-11, G=bits 10-5, B=bits 4-0)
            r = frame[:, :, 0].astype(np.uint16)
            g = frame[:, :, 1].astype(np.uint16)
            b = frame[:, :, 2].astype(np.uint16)
            rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            raw = ((rgb565 & 0xFF) << 8) | (rgb565 >> 8)
            set_window()
            send_data(raw.tobytes())
            print("Camera frame displayed!")
            time.sleep(3)
        else:
            print("Failed to capture camera frame")

        print("\nAll tests passed!")
        fill_color(0, 0, 0)

    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup()
