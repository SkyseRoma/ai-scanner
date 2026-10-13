"""
Waveshare UPS Module 3S battery / power test (INA219 over I2C).

Wiring:
  5V  -> 5V  (pin 2 or 4)
  GND -> GND (pin 6 or 9)
  SDA -> GPIO2 (pin 3)
  SCL -> GPIO3 (pin 5)

Chip: INA219 (typical address 0x40).
Reads bus voltage, shunt voltage, current, power; estimates 3S battery %.

Run: python3 test_ups.py
     python3 test_ups.py --loop
     python3 test_ups.py --raw
"""

import os
import sys
import time
import argparse
import subprocess

I2C_BUS = 1
INA219_ADDR = 0x40

# INA219 registers
REG_CONFIG = 0x00
REG_SHUNT_VOLTAGE = 0x01
REG_BUS_VOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

# Shunt resistor (ohm). Adafruit demo default 0.1.
# Waveshare board may differ — verify with --raw / schematic if current looks wrong.
R_SHUNT = 0.1

# 3S Li-ion pack: 3.0 V/cell empty -> 9.0 V, 4.2 V/cell full -> 12.6 V
V_EMPTY = 9.0
V_FULL = 12.6


def section(title):
    print(f"\n{'=' * 50}")
    print(title)
    print('=' * 50)


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except Exception as e:
        return 1, "", str(e)


def open_smbus():
    """Import smbus2 or smbus, return SMBus(1)."""
    try:
        from smbus2 import SMBus
    except ImportError:
        try:
            from smbus import SMBus
        except ImportError:
            return None
    return SMBus(I2C_BUS)


def check_i2c():
    section("1. I2C bus")
    dev = f"/dev/i2c-{I2C_BUS}"
    if not os.path.exists(dev):
        print(f"[FAIL] {dev} not found")
        print("  Fix: enable I2C (config.txt: dtparam=i2c_arm=on) and reboot")
        return False
    print(f"[OK] {dev} present")

    rc, out, err = run(["i2cdetect", "-y", str(I2C_BUS)])
    if rc != 0:
        print(f"[WARN] i2cdetect failed: {err.strip() or out.strip()}")
    else:
        print(out.strip())
    return True


def find_addr(bus):
    """Probe common INA219 addresses, then full bus scan."""
    section("2. INA219 address")
    candidates = [INA219_ADDR, 0x41, 0x44, 0x45]

    def responds(addr):
        try:
            bus.read_byte(addr)
            return True
        except Exception:
            try:
                bus.write_quick(addr)
                return True
            except Exception:
                return False

    for addr in candidates:
        if responds(addr):
            print(f"[OK] device responds at 0x{addr:02x}")
            return addr

    print("[WARN] nothing at typical INA219 addresses, full scan 0x03-0x77...")
    found = []
    for addr in range(0x03, 0x78):
        if responds(addr):
            found.append(addr)
    if found:
        for addr in found:
            print(f"[OK] device responds at 0x{addr:02x}")
        return found[0]

    print(f"[FAIL] I2C bus {I2C_BUS} is empty (checked {['0x%02x' % a for a in candidates]} + full range)")
    print("  Checklist:")
    print("  1. SDA -> GPIO2 (pin 3), SCL -> GPIO3 (pin 5)")
    print("  2. Shared GND between UPS and RPi")
    print("  3. UPS switched on / batteries active (BOOT button if first use)")
    print("  4. i2cdetect -y 1 (install i2c-tools) from another terminal")
    return None


def read_reg16(bus, addr, reg):
    """Read 16-bit register (word may be swapped on RPi SMBus)."""
    raw = bus.read_word_data(addr, reg)
    # SMBus word is little-endian; INA219 registers are big-endian
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def write_reg16(bus, addr, reg, value):
    swapped = ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
    bus.write_word_data(addr, reg, swapped)


def to_signed16(v):
    return v - 0x10000 if v > 0x7FFF else v


def calibrate(bus, addr):
    """Set calibration for R_SHUNT. Current_LSB = 0.01 A (10 mA)."""
    current_lsb = 0.01  # A per bit
    cal = int(0.04096 / (current_lsb * R_SHUNT))
    if cal < 1 or cal > 0xFFFF:
        print(f"[WARN] calibration value out of range: {cal}")
        return current_lsb
    write_reg16(bus, addr, REG_CALIBRATION, cal)
    return current_lsb


def read_status(bus, addr, current_lsb):
    """Return dict with measurements."""
    shunt_raw = to_signed16(read_reg16(bus, addr, REG_SHUNT_VOLTAGE))
    bus_raw = read_reg16(bus, addr, REG_BUS_VOLTAGE)
    power_raw = read_reg16(bus, addr, REG_POWER)
    current_raw = to_signed16(read_reg16(bus, addr, REG_CURRENT))
    cal_raw = read_reg16(bus, addr, REG_CALIBRATION)

    shunt_v = shunt_raw * 0.00001          # 10 uV
    bus_v = (bus_raw >> 3) * 0.004         # 4 mV
    current_a = current_raw * current_lsb
    power_w = power_raw * 20 * current_lsb
    overflow = bool(bus_raw & 0x1)
    conv_ready = bool(bus_raw & 0x2)

    percent = (bus_v - V_EMPTY) / (V_FULL - V_EMPTY) * 100.0
    percent = max(0.0, min(100.0, percent))

    return {
        "bus_v": bus_v,
        "shunt_v": shunt_v,
        "current_a": current_a,
        "power_w": power_w,
        "percent": percent,
        "cal_raw": cal_raw,
        "overflow": overflow,
        "conv_ready": conv_ready,
        "raw": {
            "shunt": shunt_raw,
            "bus": bus_raw,
            "power": power_raw,
            "current": current_raw,
            "cal": cal_raw,
        },
    }


def print_status(addr, st, show_raw=False):
    print(f"\nINA219 @ 0x{addr:02x}")
    print(f"  Bus voltage:   {st['bus_v']:.3f} V")
    print(f"  Shunt voltage: {st['shunt_v'] * 1000:.2f} mV")
    print(f"  Current:       {st['current_a'] * 1000:.1f} mA")
    print(f"  Power:         {st['power_w']:.3f} W")
    print(f"  Battery 3S:    {st['percent']:.0f}%  (~{st['bus_v']:.2f} V, {V_EMPTY}-{V_FULL} V linear)")
    if st["overflow"]:
        print("  [WARN] math overflow bit set")
    if show_raw:
        print("  Raw registers:")
        for k, v in st["raw"].items():
            print(f"    {k:8s} 0x{v:04x} ({v})")


def main():
    parser = argparse.ArgumentParser(description="UPS Module 3S (INA219) test")
    parser.add_argument("--loop", nargs="?", const=2.0, type=float, metavar="SEC",
                        help="continuous read every SEC seconds (default 2)")
    parser.add_argument("--raw", action="store_true", help="print raw register values")
    args = parser.parse_args()

    print("Waveshare UPS Module 3S / INA219 test")
    print(f"I2C bus: {I2C_BUS}, R_shunt: {R_SHUNT} ohm")

    if not check_i2c():
        sys.exit(1)

    bus = open_smbus()
    if bus is None:
        section("Result")
        print("[FAIL] smbus2/smbus not installed")
        print("  Fix: pip install smbus2   (or apt install python3-smbus)")
        sys.exit(1)

    try:
        addr = find_addr(bus)
        if addr is None:
            section("Result")
            sys.exit(1)

        section("3. Measurements")
        current_lsb = calibrate(bus, addr)
        print(f"[OK] calibrated, Current_LSB={current_lsb} A/LSB, R_shunt={R_SHUNT}")

        if args.loop:
            print(f"\nLoop every {args.loop}s — Ctrl+C to stop")
            try:
                while True:
                    st = read_status(bus, addr, current_lsb)
                    print_status(addr, st, show_raw=args.raw)
                    time.sleep(args.loop)
            except KeyboardInterrupt:
                print("\nAborted.")
                sys.exit(130)
        else:
            st = read_status(bus, addr, current_lsb)
            print_status(addr, st, show_raw=args.raw)

        section("Result")
        print("[OK] UPS I2C read successful")
        print(f"     Battery ≈ {st['percent']:.0f}% at {st['bus_v']:.2f} V")
        sys.exit(0)

    finally:
        try:
            bus.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
