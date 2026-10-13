"""
WiFi fallback daemon: if no known WiFi network, start access point Scanner-AP.
Optional: exit AP mode when a saved network appears.

Run: python3 tools/wifi_fallback.py
     python3 tools/wifi_fallback.py --once

systemd unit example:
  ExecStart=/usr/bin/python3 /home/pi/PROJECTS/scanner/tools/wifi_fallback.py
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules import wifi

CHECK_EVERY_S = 15
RETRY_AP_S = 60
AP_SSID = "Scanner-AP"
AP_PASSWORD = "scanner123"


def load_ap_from_settings():
    global AP_SSID, AP_PASSWORD
    try:
        import json
        path = os.path.join(os.path.dirname(__file__), "..", "data", "settings.json")
        with open(path) as f:
            s = json.load(f)
        AP_SSID = s.get("wifi_ap_ssid") or AP_SSID
        AP_PASSWORD = s.get("wifi_ap_password") or AP_PASSWORD
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="WiFi hotspot fallback")
    parser.add_argument("--once", action="store_true", help="single check then exit")
    args = parser.parse_args()

    load_ap_from_settings()
    print(f"[wifi_fallback] AP={AP_SSID} check every {CHECK_EVERY_S}s")

    last_ap_try = 0.0
    while True:
        try:
            if wifi.has_known_client():
                # If AP is up but known client is preferred, leave AP
                st = wifi.get_status()
                if st.get("hotspot"):
                    print("[wifi_fallback] known network available, leaving AP mode")
                    wifi.stop_hotspot()
            else:
                now = time.time()
                if now - last_ap_try >= RETRY_AP_S:
                    r = wifi.ensure_fallback(ap_ssid=AP_SSID, ap_password=AP_PASSWORD)
                    print(f"[wifi_fallback] {r}")
                    last_ap_try = now
        except Exception as e:
            print(f"[wifi_fallback] error: {e}")

        if args.once:
            break
        time.sleep(CHECK_EVERY_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped")
