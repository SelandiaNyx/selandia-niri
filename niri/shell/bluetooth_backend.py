"""Pure BlueZ D-Bus backend (zero bluetoothctl dependency): scan, pair, connect, battery."""
from __future__ import annotations

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from i18n import tr


def _bus():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def _call(path: str, interface: str, method: str, params=None, *, timeout_ms: int = 12000):
    try:
        return _bus().call_sync(
            "org.bluez", path, interface, method,
            params, None, Gio.DBusCallFlags.NONE, timeout_ms, None,
        )
    except GLib.Error as error:
        raise RuntimeError(error.message or str(error)) from error


def _set_prop(path: str, interface: str, prop: str, variant: GLib.Variant):
    _call(path, "org.freedesktop.DBus.Properties", "Set",
          GLib.Variant("(ssv)", (interface, prop, variant)), timeout_ms=8000)


def read_state() -> dict:
    """Read BlueZ adapter(s), paired/connected/discovered devices, and battery levels."""
    try:
        res = _bus().call_sync(
            "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects", None, GLib.VariantType.new("(a{oa{sa{sv}}})"),
            Gio.DBusCallFlags.NONE, 3000, None,
        )
        objects = res.unpack()[0]
    except GLib.Error as error:
        return {"available": False, "error": error.message or str(error), "adapter": None, "devices": []}

    adapters = []
    devices = []
    for path, ifaces in objects.items():
        adapter = ifaces.get("org.bluez.Adapter1")
        if adapter is not None:
            adapters.append({
                "path": path,
                "name": str(adapter.get("Alias") or adapter.get("Name") or path),
                "address": str(adapter.get("Address") or ""),
                "powered": bool(adapter.get("Powered", False)),
                "discovering": bool(adapter.get("Discovering", False)),
                "discoverable": bool(adapter.get("Discoverable", False)),
            })
        dev = ifaces.get("org.bluez.Device1")
        if dev is not None:
            batt = ifaces.get("org.bluez.Battery1") or {}
            name = str(dev.get("Alias") or dev.get("Name") or dev.get("Address") or "").strip()
            if not name:
                continue
            devices.append({
                "path": path,
                "adapter": str(dev.get("Adapter") or ""),
                "address": str(dev.get("Address") or ""),
                "name": name,
                "icon": str(dev.get("Icon") or "bluetooth-active"),
                "paired": bool(dev.get("Paired", False)),
                "connected": bool(dev.get("Connected", False)),
                "trusted": bool(dev.get("Trusted", False)),
                "rssi": dev.get("RSSI"),
                "battery": int(batt["Percentage"]) if "Percentage" in batt else None,
            })

    adapters.sort(key=lambda a: (not a["powered"], a["path"]))
    primary = adapters[0] if adapters else None
    if primary:
        devices = [d for d in devices if not d["adapter"] or d["adapter"] == primary["path"]]
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], -(d["rssi"] or -999), d["name"].casefold()))
    return {"available": primary is not None, "error": "", "adapter": primary, "devices": devices}


def set_power(adapter_path: str, powered: bool) -> None:
    _set_prop(adapter_path, "org.bluez.Adapter1", "Powered", GLib.Variant("b", bool(powered)))


def set_discovery(adapter_path: str, active: bool) -> None:
    try:
        _call(adapter_path, "org.bluez.Adapter1", "StartDiscovery" if active else "StopDiscovery", timeout_ms=5000)
    except RuntimeError as err:
        # Ignore benign "already in progress" / "no discovery started" states.
        msg = str(err).lower()
        if "in progress" in msg or "no discovery" in msg:
            return
        raise


def pair_device(device_path: str) -> None:
    _call(device_path, "org.bluez.Device1", "Pair", timeout_ms=25000)


def connect_device(device_path: str, connect: bool) -> None:
    _call(device_path, "org.bluez.Device1", "Connect" if connect else "Disconnect", timeout_ms=15000)


def set_trusted(device_path: str, trusted: bool) -> None:
    _set_prop(device_path, "org.bluez.Device1", "Trusted", GLib.Variant("b", bool(trusted)))


def remove_device(adapter_path: str, device_path: str) -> None:
    if not adapter_path or not device_path:
        raise ValueError(tr("Invalid Bluetooth device", "无效的蓝牙设备"))
    _call(adapter_path, "org.bluez.Adapter1", "RemoveDevice", GLib.Variant("(o)", (device_path,)), timeout_ms=10000)
