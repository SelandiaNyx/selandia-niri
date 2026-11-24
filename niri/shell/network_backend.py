"""Native NetworkManager (nmcli) backend: Wi-Fi scan/join, IP/DNS, VPN & hotspot."""
from __future__ import annotations

import os
import shutil
import subprocess

from i18n import tr

ENV = dict(os.environ, LC_ALL="C")


def _run(argv: list[str], *, timeout: int = 12, check: bool = True) -> str:
    if not shutil.which("nmcli"):
        raise RuntimeError(tr("NetworkManager (nmcli) is not installed", "未安装 NetworkManager（nmcli）"))
    res = subprocess.run(["nmcli", *argv], capture_output=True, text=True, env=ENV, timeout=timeout)
    if check and res.returncode != 0:
        detail = (res.stderr or res.stdout).strip()[-280:]
        raise RuntimeError(detail or tr("Network command failed", "网络操作失败"))
    return res.stdout


def _split_terse(line: str, expected: int) -> list[str]:
    """Split nmcli --terse escaped colon-separated fields."""
    fields: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf))
    while len(fields) < expected:
        fields.append("")
    return fields[:expected]


def read_state(*, rescan: bool = False) -> dict:
    """Return Wi-Fi radio, active interfaces, scanned Wi-Fi APs and saved profiles."""
    if not shutil.which("nmcli"):
        return {"available": False, "wifi_enabled": False, "active": [], "aps": [], "profiles": [], "hotspot_active": False}
    radio = _run(["radio", "wifi"], check=False).strip().lower()
    wifi_enabled = radio == "enabled"

    # Saved & active profiles
    prof_raw = _run(["-t", "-f", "UUID,NAME,TYPE,DEVICE,AUTOCONNECT", "connection", "show"], check=False)
    profiles = []
    hotspot_active = False
    for line in prof_raw.splitlines():
        if not line.strip():
            continue
        uuid, name, ctype, dev, auto = _split_terse(line, 5)
        if not uuid:
            continue
        active = bool(dev and dev != "--")
        if active and name.lower() == "hotspot":
            hotspot_active = True
        profiles.append({
            "id": uuid, "name": name, "type": ctype, "device": dev if active else "",
            "active": active, "autoconnect": auto == "yes",
        })
    profiles.sort(key=lambda item: (not item["active"], item["name"].casefold()))

    # Active device IP / DNS details
    dev_raw = _run(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], check=False)
    active_devs = []
    for line in dev_raw.splitlines():
        if not line.strip():
            continue
        dev, dtype, state, conn = _split_terse(line, 4)
        if dtype == "loopback" or not state.startswith("connected"):
            continue
        detail_raw = _run(["-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,GENERAL.HWADDR", "device", "show", dev], check=False)
        info = {"device": dev, "type": dtype, "connection": conn, "ip4": "", "gateway": "", "dns": [], "mac": ""}
        for dline in detail_raw.splitlines():
            if ":" not in dline:
                continue
            k, v = dline.split(":", 1)
            v = v.strip()
            if not v or v == "--":
                continue
            if k.startswith("IP4.ADDRESS") and not info["ip4"]:
                info["ip4"] = v
            elif k == "IP4.GATEWAY":
                info["gateway"] = v
            elif k.startswith("IP4.DNS"):
                info["dns"].append(v)
            elif k == "GENERAL.HWADDR":
                info["mac"] = v
        active_devs.append(info)

    # Scanned Wi-Fi access points (deduplicated by SSID keeping strongest signal)
    aps = []
    if wifi_enabled:
        ap_args = ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ", "device", "wifi", "list"]
        if rescan:
            ap_args.extend(["--rescan", "yes"])
        ap_raw = _run(ap_args, timeout=16, check=False)
        by_ssid: dict[str, dict] = {}
        for line in ap_raw.splitlines():
            if not line.strip():
                continue
            in_use, ssid, sig, sec, freq = _split_terse(line, 5)
            ssid = ssid.strip()
            if not ssid:
                continue
            try:
                signal = int(sig)
            except ValueError:
                signal = 0
            entry = {
                "ssid": ssid, "signal": signal, "security": sec.strip() or tr("Open", "开放"),
                "secured": bool(sec.strip() and sec.strip() != "--"), "in_use": in_use.strip() == "*",
                "freq": freq.strip(),
            }
            prev = by_ssid.get(ssid)
            if prev is None or entry["in_use"] or (not prev["in_use"] and entry["signal"] > prev["signal"]):
                by_ssid[ssid] = entry
        aps = sorted(by_ssid.values(), key=lambda x: (not x["in_use"], -x["signal"], x["ssid"].casefold()))

    return {
        "available": True, "wifi_enabled": wifi_enabled, "active": active_devs,
        "aps": aps, "profiles": profiles, "hotspot_active": hotspot_active,
    }


def set_wifi_radio(enabled: bool) -> None:
    _run(["radio", "wifi", "on" if enabled else "off"], timeout=10)


def connect_wifi(ssid: str, password: str = "") -> None:
    ssid = ssid.strip()
    if not ssid:
        raise ValueError(tr("Wi-Fi name is empty", "无线网络名称不能为空"))
    argv = ["device", "wifi", "connect", ssid]
    if password:
        argv.extend(["password", password])
    _run(argv, timeout=25)


def activate_profile(uuid: str, enabled: bool) -> None:
    _run(["connection", "up" if enabled else "down", "uuid", uuid], timeout=20)


def forget_profile(uuid: str) -> None:
    _run(["connection", "delete", "uuid", uuid], timeout=12)


def toggle_hotspot(enabled: bool, ssid: str = "Selandia-Hotspot", password: str = "") -> None:
    if not enabled:
        _run(["connection", "down", "Hotspot"], timeout=12, check=False)
        return
    argv = ["device", "wifi", "hotspot", "ssid", ssid.strip() or "Selandia-Hotspot"]
    if password and len(password) >= 8:
        argv.extend(["password", password])
    _run(argv, timeout=20)
