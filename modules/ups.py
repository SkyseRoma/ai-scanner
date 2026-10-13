"""
Waveshare UPS Module 3S battery monitor (INA219 over I2C).

Used by main loop (display icon) and Web UI (detailed stats).
"""

import time

I2C_BUS = 1
REG_SHUNT_VOLTAGE = 0x01
REG_BUS_VOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

R_SHUNT = 0.1
V_EMPTY = 9.0
V_FULL = 12.6
ADDR_CANDIDATES = (0x41, 0x40, 0x44, 0x45)


class UPS:
    def __init__(self, bus_id=I2C_BUS, addr=None):
        self.bus_id = bus_id
        self.addr = addr
        self._bus = None
        self.current_lsb = 0.01
        self.available = False
        self.error = None
        self._connect()

    def _open_bus(self):
        try:
            from smbus2 import SMBus
        except ImportError:
            try:
                from smbus import SMBus
            except ImportError:
                self.error = "smbus2/smbus not installed"
                return None
        try:
            return SMBus(self.bus_id)
        except Exception as e:
            self.error = str(e)
            return None

    def _connect(self):
        self._bus = self._open_bus()
        if self._bus is None:
            return
        if self.addr is None:
            self.addr = self._scan()
        if self.addr is None:
            self.error = self.error or "INA219 not found on I2C"
            self.available = False
            return
        try:
            self._calibrate()
            self.available = True
            self.error = None
        except Exception as e:
            self.error = str(e)
            self.available = False

    def _scan(self):
        for addr in ADDR_CANDIDATES:
            try:
                self._bus.read_byte(addr)
                return addr
            except Exception:
                continue
        try:
            for addr in range(0x03, 0x78):
                self._bus.read_byte(addr)
                return addr
        except Exception:
            pass
        return None

    def _read16(self, reg):
        raw = self._bus.read_word_data(self.addr, reg)
        return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)

    def _write16(self, reg, value):
        swapped = ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
        self._bus.write_word_data(self.addr, reg, swapped)

    def _calibrate(self):
        cal = int(0.04096 / (self.current_lsb * R_SHUNT))
        if 1 <= cal <= 0xFFFF:
            self._write16(REG_CALIBRATION, cal)

    def read_status(self):
        """Return dict or None. Keys: voltage_v, percent, current_a, power_w, charging, available."""
        if not self.available or self._bus is None:
            return {
                "available": False,
                "error": self.error or "UPS not available",
            }
        try:
            shunt_raw = self._read16(REG_SHUNT_VOLTAGE)
            if shunt_raw > 0x7FFF:
                shunt_raw -= 0x10000
            bus_raw = self._read16(REG_BUS_VOLTAGE)
            power_raw = self._read16(REG_POWER)
            current_raw = self._read16(REG_CURRENT)
            if current_raw > 0x7FFF:
                current_raw -= 0x10000

            voltage = (bus_raw >> 3) * 0.004
            current = current_raw * self.current_lsb
            power = power_raw * 20 * self.current_lsb
            percent = (voltage - V_EMPTY) / (V_FULL - V_EMPTY) * 100.0
            percent = max(0.0, min(100.0, percent))
            # positive shunt current = charging (into battery) on this board
            charging = current > 0.02

            return {
                "available": True,
                "voltage_v": round(voltage, 3),
                "current_a": round(current, 3),
                "power_w": round(power, 3),
                "percent": round(percent, 1),
                "charging": charging,
                "addr": self.addr,
                "v_min": V_EMPTY,
                "v_max": V_FULL,
            }
        except Exception as e:
            self.error = str(e)
            return {"available": False, "error": str(e)}

    def close(self):
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None
