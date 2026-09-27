import time
import spidev
import numpy as np
import lgpio


class PiCameraDisplay:
    """ILI9341 display control via SPI."""
    
    def __init__(self, width=320, height=240, dc_pin=24, rst_pin=25, spi_bus=0, spi_device=0, spi_speed=40000000):
        self.width = width
        self.height = height
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        
        self._gpio = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(self._gpio, self.dc_pin)
        lgpio.gpio_claim_output(self._gpio, self.rst_pin)
        
        self._init_spi(spi_bus, spi_device, spi_speed)
        self._init_ili9341()

    def _init_spi(self, bus, device, speed):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = speed
        self.spi.mode = 0b00

    def _send_cmd(self, cmd):
        lgpio.gpio_write(self._gpio, self.dc_pin, 0)
        self.spi.writebytes([cmd])

    def _send_data(self, data):
        lgpio.gpio_write(self._gpio, self.dc_pin, 1)
        if isinstance(data, list):
            self.spi.writebytes(data)
        else:
            self.spi.writebytes2(data)

    def _init_ili9341(self):
        lgpio.gpio_write(self._gpio, self.rst_pin, 0)
        time.sleep(0.1)
        lgpio.gpio_write(self._gpio, self.rst_pin, 1)
        time.sleep(0.1)

        self._send_cmd(0x01)  # Software Reset
        time.sleep(0.1)
        self._send_cmd(0x28)  # Display OFF

        self._send_cmd(0x36)  # MADCTL
        self._send_data([0x28])

        self._send_cmd(0x3A)  # Pixel Format
        self._send_data([0x55])  # RGB565

        self._send_cmd(0x11)  # Exit Sleep
        time.sleep(0.1)
        self._send_cmd(0x29)  # Display ON

    def _set_window(self, x0=0, y0=0, x1=None, y1=None):
        """Set display window. Defaults to full screen."""
        if x1 is None: x1 = self.width - 1
        if y1 is None: y1 = self.height - 1
        self._send_cmd(0x2A)
        self._send_data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._send_cmd(0x2B)
        self._send_data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._send_cmd(0x2C)

    def cleanup(self):
        print("Cleaning up display resources...")
        try:
            self.spi.close()
        except Exception:
            pass
        try:
            lgpio.gpiochip_close(self._gpio)
        except Exception:
            pass