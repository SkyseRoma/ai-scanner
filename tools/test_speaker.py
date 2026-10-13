"""
Speaker voice test — plays the same sample through the speaker (I2S / PulseAudio).
For A/B comparison: run once per speaker.

Run: python3 test_speaker.py
"""

import os
import sys
import subprocess

SAMPLES = [
    os.path.join(os.path.dirname(__file__), "..", "data", "database",
                 "2026-09-27_16-34-34", "audio.mp3"),
    os.path.join(os.path.dirname(__file__), "..", "data", "database",
                 "2026-09-27_16-38-30", "audio.mp3"),
]


def play(path):
    print(f"\nPlaying: {path}")
    for cmd in (["paplay", path], ["aplay", path]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                print(f"OK via {cmd[0]}")
                return True
            print(f"{cmd[0]} failed: {r.stderr.strip()}")
        except FileNotFoundError:
            print(f"{cmd[0]} not found")
    return False


def main():
    print("Speaker voice test")
    print("Default sink:", end=" ")
    subprocess.run(["pactl", "get-default-sink"], check=False)

    files = [p for p in SAMPLES if os.path.exists(p)]
    if not files:
        print("No sample files found in data/database/")
        sys.exit(1)

    while True:
        print("\n1 — short sample")
        print("2 — longer sample")
        print("3 — play all")
        print("q — quit")
        choice = input("Select: ").strip().lower()

        if choice == "q":
            break
        elif choice == "1":
            play(files[0])
        elif choice == "2":
            play(files[-1] if len(files) > 1 else files[0])
        elif choice == "3":
            for p in files:
                play(p)
        else:
            print("Unknown option")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
