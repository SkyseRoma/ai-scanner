"""
WiFi management via NetworkManager (nmcli): scan, connect, hotspot fallback.
"""

import subprocess
import time


def _run(cmd, timeout=30, sudo=False):
    try:
        full = (["sudo", "-n"] + list(cmd)) if sudo else list(cmd)
        p = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def get_status():
    rc, out, _ = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    devices = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4:
            devices.append({
                "device": parts[0],
                "type": parts[1],
                "state": parts[2],
                "connection": parts[3],
            })
    wlan = next((d for d in devices if d["type"] == "wifi"), None)
    return {
        "devices": devices,
        "wlan_state": wlan["state"] if wlan else "missing",
        "wlan_connection": wlan["connection"] if wlan else "",
        "hotspot": bool(wlan and wlan["connection"] in ("Scanner-AP", "scanner-ap")),
    }


def _scan_once():
    _run(["nmcli", "device", "wifi", "rescan"], timeout=15)
    rc, out, err = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"], timeout=20)
    if rc != 0:
        return {"ok": False, "error": err or out, "networks": []}
    networks = []
    seen = set()
    for line in out.splitlines():
        # nmcli -t escapes ':' in SSID as '\:'
        parts = []
        buf = ""
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                buf += line[i + 1]
                i += 2
                continue
            if line[i] == ":":
                parts.append(buf)
                buf = ""
            else:
                buf += line[i]
            i += 1
        parts.append(buf)
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts[0], parts[1], parts[2], parts[3]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append({
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "security": security,
            "active": in_use == "*",
        })
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return {"ok": True, "networks": networks}


def scan_networks(allow_ap_drop=False):
    """
    Scan nearby APs. In hotspot mode the radio cannot scan —
    return empty list with ap_mode flag (UI shows manual SSID entry instead).
    """
    st = get_status()
    if st.get("hotspot"):
        return {
            "ok": True,
            "networks": [],
            "ap_mode": True,
            "note": "AP mode: enter SSID manually",
        }
    return _scan_once()


def connect(ssid, password=None):
    if not ssid:
        return {"ok": False, "error": "SSID required"}
    st = get_status()
    was_ap = st.get("hotspot")
    if was_ap:
        # hotspot holds the radio — drop AP so the client can find the target SSID
        stop_hotspot()
        time.sleep(1.5)
        _run(["nmcli", "device", "wifi", "rescan"], timeout=15, sudo=True)
        time.sleep(2.0)
    # drop existing profile with same name if any
    _run(["nmcli", "connection", "delete", ssid], timeout=10, sudo=True)
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    rc, out, err = _run(cmd, timeout=45, sudo=True)
    if rc == 0:
        return {"ok": True, "message": out or f"Connected to {ssid}"}
    # restore AP if connect failed and we were in AP mode
    if was_ap:
        try:
            import json, os
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "settings.json")
            with open(path) as f:
                s = json.load(f)
            start_hotspot(s.get("wifi_ap_ssid") or "Scanner-AP", s.get("wifi_ap_password") or "scanner123")
        except Exception:
            start_hotspot()
    return {"ok": False, "error": err or out or "connect failed"}


def start_hotspot(ssid="Scanner-AP", password="scanner123"):
    if len(password or "") < 8:
        password = "scanner123"
    # remove old hotspot connection
    _run(["nmcli", "connection", "delete", "Scanner-AP"], timeout=10, sudo=True)
    rc, out, err = _run([
        "nmcli", "device", "wifi", "hotspot",
        "ifname", "wlan0",
        "con-name", "Scanner-AP",
        "ssid", ssid,
        "password", password,
    ], timeout=30, sudo=True)
    if rc == 0:
        return {"ok": True, "ssid": ssid, "message": out or "hotspot started"}
    return {"ok": False, "error": err or out or "hotspot failed"}


def stop_hotspot():
    _run(["nmcli", "connection", "down", "Scanner-AP"], timeout=15, sudo=True)
    _run(["nmcli", "connection", "delete", "Scanner-AP"], timeout=10, sudo=True)
    return {"ok": True}


def has_known_client():
    """True if wlan is connected to a non-hotspot network."""
    st = get_status()
    if st.get("hotspot"):
        return False
    return st.get("wlan_state") == "connected"


def ensure_fallback(wifi_ok=None, ap_ssid="Scanner-AP", ap_password="scanner123", log=print):
    """
    If WiFi is not connected to a known network, start hotspot.
    Returns dict with action: none|hotspot|ok
    """
    if wifi_ok is None:
        wifi_ok = has_known_client()
    if wifi_ok:
        return {"action": "none"}
    st = get_status()
    if st.get("hotspot"):
        return {"action": "ok", "note": "hotspot already active"}
    log("[wifi] no known network — starting hotspot")
    r = start_hotspot(ap_ssid, ap_password)
    r["action"] = "hotspot" if r.get("ok") else "error"
    return r
