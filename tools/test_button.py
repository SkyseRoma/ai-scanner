"""
Button test on Raspberry Pi 5.
Wiring: GPIO17 (pin 11) -> button -> GND (pin 14)
Run: python3 test_button.py
"""

import RPi.GPIO as GPIO
import time

BTN_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(BTN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Button test")
print(f"Pin: GPIO{BTN_PIN} (pin 11)")
print("Wiring: GPIO17 -> button -> GND")
print("Press the button (Ctrl+C to exit)")
print("-" * 30)

press_count = 0

try:
    while True:
        state = GPIO.input(BTN_PIN)
        if state == GPIO.LOW:
            press_count += 1
            print(f"[{press_count}] Pressed!")
            # Wait for release (debounce)
            while GPIO.input(BTN_PIN) == GPIO.LOW:
                time.sleep(0.05)
            time.sleep(0.1)  # debounce after release
        time.sleep(0.02)

except KeyboardInterrupt:
    print(f"\nExit. Total presses: {press_count}")
finally:
    GPIO.cleanup()
