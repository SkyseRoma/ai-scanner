"""
MAX98357A I2S audio test on Raspberry Pi 5.

Wiring:
  VIN  -> 3.3V (pin 1)
  GND  -> GND  (pin 39)
  BCLK -> GPIO18 (pin 12)
  LRC  -> GPIO19 (pin 35)
  DIN  -> GPIO21 (pin 40)
  SD   -> VIN (must be HIGH, unless board has pull-up)
  GAIN -> floating (9 dB)

Run: python3 test_i2s.py
"""

import os
import sys
import math
import struct
import wave
import subprocess
import tempfile
import time

CONFIG_TXT = "/boot/firmware/config.txt"
if not os.path.exists(CONFIG_TXT):
    CONFIG_TXT = "/boot/config.txt"

SAMPLE_RATE = 44100
DURATION_S = 2.0
TONE_HZ = 440.0


def section(title):
    print(f"\n{'=' * 50}")
    print(title)
    print('=' * 50)


def run(cmd):
    """Run command, return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except Exception as e:
        return 1, "", str(e)


def check_config():
    """Check /boot/firmware/config.txt for I2S overlay."""
    section("1. config.txt (I2S overlay)")
    if not os.path.exists(CONFIG_TXT):
        print(f"[FAIL] {CONFIG_TXT} not found")
        return False

    with open(CONFIG_TXT) as f:
        lines = f.readlines()

    has_hifiberry = False
    audio_off = False
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("#") or not s:
            continue
        if "hifiberry" in s.lower() or "i2s" in s.lower() or "max98357" in s.lower():
            print(f"  {i}: {s}")
            has_hifiberry = True
        if s.replace(" ", "") in ("dtparam=audio=off", "dtparam=audio=0"):
            print(f"  {i}: {s}")
            audio_off = True

    if not has_hifiberry:
        print("[FAIL] No I2S overlay found (expected dtoverlay=hifiberry-dac)")
        print("  Fix — add to", CONFIG_TXT, ":")
        print("    dtparam=audio=off")
        print("    dtoverlay=hifiberry-dac")
        return False

    if not audio_off:
        print("[WARN] dtparam=audio=off not found (onboard audio may conflict)")

    print("[OK] I2S overlay present")
    return True


def check_cards():
    """Check ALSA sound cards."""
    section("2. ALSA sound cards")
    rc, out, err = run(["aplay", "-l"])
    if rc != 0:
        print(f"[FAIL] aplay -l: {err.strip() or out.strip()}")
        return None

    print(out.strip() or "(no output)")
    if "no soundcards" in out.lower() or not out.strip():
        print("[FAIL] No sound cards — I2S not loaded (reboot after config.txt edit)")
        return None

    # Prefer HifiBerry / MAX98357 / pcm5102a card
    card = None
    for line in out.splitlines():
        line_l = line.lower()
        if "card" in line_l and ("hifiberry" in line_l or "max98357" in line_l
                                 or "pcm5102" in line_l or "i2s" in line_l):
            # e.g. "card 0: sndrpihifiberry [snd_rpi_hifiberry_dac], device 0: ..."
            try:
                card = int(line.split("card")[1].split(":")[0].strip())
            except Exception:
                pass
            break

    if card is None:
        # Fallback: first card
        for line in out.splitlines():
            if line.strip().startswith("card "):
                try:
                    card = int(line.split("card")[1].split(":")[0].strip())
                except Exception:
                    pass
                break

    if card is None:
        print("[FAIL] Could not parse card number")
    else:
        print(f"[OK] Using card {card}")
    return card


def make_tone(path, freq=TONE_HZ, duration=DURATION_S, rate=SAMPLE_RATE):
    """Write a stereo 16-bit sine WAV."""
    n = int(rate * duration)
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            # Fade in/out 50 ms to avoid clicks
            t = i / rate
            env = 1.0
            fade = 0.05
            if t < fade:
                env = t / fade
            elif t > duration - fade:
                env = (duration - t) / fade
            val = int(0.4 * env * 32767 * math.sin(2 * math.pi * freq * t))
            frames += struct.pack("<hh", val, val)
        w.writeframes(frames)
    return path


def play_aplay(card, path):
    """Play WAV via aplay on I2S card."""
    section("3. aplay (ALSA direct)")
    dev = f"plughw:{card},0"
    print(f"Device: {dev}")
    print(f"File:   {path}")
    rc, out, err = run(["aplay", "-D", dev, path])
    if rc == 0:
        print("[OK] aplay finished")
        return True
    print(f"[FAIL] aplay rc={rc}: {err.strip() or out.strip()}")
    # Fallback: default device
    print("Trying default device...")
    rc, out, err = run(["aplay", path])
    if rc == 0:
        print("[OK] aplay (default) finished")
        return True
    print(f"[FAIL] aplay default rc={rc}: {err.strip() or out.strip()}")
    return False


def play_paplay(path):
    """Play WAV via PulseAudio (if available)."""
    section("4. paplay (PulseAudio)")
    rc, out, err = run(["pactl", "info"])
    if rc != 0:
        print("[SKIP] PulseAudio not available")
        return None

    print("Sinks:")
    rc, out, err = run(["pactl", "list", "short", "sinks"])
    print(out.strip() or "(none)")

    # Try to find an i2s / hifiberry sink and set default
    rc, out, err = run(["pactl", "list", "short", "sinks"])
    for line in out.splitlines():
        if any(k in line.lower() for k in ("i2s", "hifiberry", "max98357", "alsa_output.platform")):
            sink = line.split()[1]
            print(f"Setting default sink: {sink}")
            run(["pactl", "set-default-sink", sink])
            break

    rc, out, err = run(["paplay", path])
    if rc == 0:
        print("[OK] paplay finished")
        return True
    print(f"[FAIL] paplay rc={rc}: {err.strip() or out.strip()}")
    return False


def check_mute():
    """Unmute ALSA mixer for I2S card."""
    section("5. Mixer")
    rc, out, err = run(["amixer", "sget", "PCM"])
    if rc == 0:
        print(out.strip())
        if "[off]" in out:
            print("Unmuting PCM...")
            run(["amixer", "sset", "PCM", "unmute"])
            run(["amixer", "sset", "PCM", "100%"])
            print("[OK] PCM unmuted")
        else:
            print("[OK] PCM not muted")
    else:
        # HifiBerry DAC has no mixer sometimes — not critical
        print("[SKIP] No 'PCM' mixer (normal for HifiBerry DAC)")


def main():
    print("MAX98357A I2S audio test")
    print("Press Ctrl+C to abort")
    time.sleep(0.5)

    ok_config = check_config()
    card = check_cards()
    check_mute()

    if card is None:
        section("Result")
        print("[FAIL] No I2S sound card. Fix config.txt and reboot:")
        print("  sudo nano " + CONFIG_TXT)
        print("  add:  dtparam=audio=off")
        print("  add:  dtoverlay=hifiberry-dac")
        print("  then: sudo reboot")
        sys.exit(1)

    tmp = os.path.join(tempfile.gettempdir(), "max98357_test.wav")
    make_tone(tmp)
    print(f"\nGenerated tone: {TONE_HZ} Hz, {DURATION_S}s, {SAMPLE_RATE} Hz")
    print(f"File: {tmp}")

    input("\nPress ENTER to play test tone via ALSA...")
    alsa_ok = play_aplay(card, tmp)

    input("\nPress ENTER to play via PulseAudio (or skip)...")
    pa_ok = play_paplay(tmp)

    section("Result")
    heard = input("Did you hear a clear 440 Hz tone? [y/N]: ").strip().lower()
    if heard in ("y", "yes", "д", "да"):
        print("[OK] MAX98357A I2S audio works!")
        print("Next: set I2S as default sink and switch tts.py from BT to I2S.")
        sys.exit(0)

    print("[FAIL] No sound. Checklist:")
    print("  1. SD pin is HIGH (jumper SD->VIN if no pull-up on board)")
    print("  2. VIN is 3.3V (pin 1), not 5V")
    print("  3. BCLK=GPIO18, LRC=GPIO19, DIN=GPIO21")
    print("  4. Speaker connected to Speaker+/Speaker- (4 ohm)")
    print("  5. config.txt has dtoverlay=hifiberry-dac and system rebooted")
    print("  6. aplay -l shows HifiBerry / pcm5102a card")
    if alsa_ok is False:
        print("  7. ALSA playback failed — check card number in aplay -l")
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
