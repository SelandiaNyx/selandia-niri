#!/usr/bin/env python3
"""Selandia Native System Agent: Polkit PAM authenticator + BlueZ Agent1.

Replaces heavy third-party desktop daemons (polkit-kde-agent ~178 MiB,
blueman-applet/tray ~127 MiB) with one ultra-lightweight GLib/D-Bus process
(~25-35 MiB RSS, 0% idle CPU) that speaks directly to:
  - ``polkitd`` via ``org.freedesktop.PolicyKit1.AuthenticationAgent`` and
    delegates 100% of PAM verification to the official setuid helper through
    ``PolkitAgent.Session`` (passwords are never stored, logged or persisted).
  - ``bluetoothd`` via ``org.bluez.Agent1`` for passkey/PIN pairing prompts.

Dialogs are created lazily on demand and inherit the active Gemini Starlight
MD3 stylesheet (dark/light, 14 palettes, eye-care mode, font scaling).
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import signal
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Polkit", "1.0")
gi.require_version("PolkitAgent", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango, Polkit, PolkitAgent

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from appearance import load_settings, mascot_asset
from control_widgets import icon, pack, prepare_icon_theme, style
from i18n import tr

POLKIT_OBJECT_PATH = "/org/selandia/PolicyKit1/AuthenticationAgent"
BLUEZ_OBJECT_PATH = "/org/selandia/BluezAgent"

POLKIT_AGENT_XML = """
<node>
  <interface name="org.freedesktop.PolicyKit1.AuthenticationAgent">
    <method name="BeginAuthentication">
      <arg name="action_id" type="s" direction="in"/>
      <arg name="message" type="s" direction="in"/>
      <arg name="icon_name" type="s" direction="in"/>
      <arg name="details" type="a{ss}" direction="in"/>
      <arg name="cookie" type="s" direction="in"/>
      <arg name="identities" type="a(sa{sv})" direction="in"/>
    </method>
    <method name="CancelAuthentication">
      <arg name="cookie" type="s" direction="in"/>
    </method>
  </interface>
</node>
"""

BLUEZ_AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode">
      <arg name="device" type="o" direction="in"/>
      <arg name="pincode" type="s" direction="out"/>
    </method>
    <method name="DisplayPinCode">
      <arg name="device" type="o" direction="in"/>
      <arg name="pincode" type="s" direction="in"/>
    </method>
    <method name="RequestPasskey">
      <arg name="device" type="o" direction="in"/>
      <arg name="passkey" type="u" direction="out"/>
    </method>
    <method name="DisplayPasskey">
      <arg name="device" type="o" direction="in"/>
      <arg name="passkey" type="u" direction="in"/>
      <arg name="entered" type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation">
      <arg name="device" type="o" direction="in"/>
      <arg name="passkey" type="u" direction="in"/>
    </method>
    <method name="RequestAuthorization">
      <arg name="device" type="o" direction="in"/>
    </method>
    <method name="AuthorizeService">
      <arg name="device" type="o" direction="in"/>
      <arg name="uuid" type="s" direction="in"/>
    </method>
    <method name="Cancel"/>
  </interface>
</node>
"""

_THEME_PROVIDERS: list[Gtk.CssProvider] = []


def reload_theme() -> dict:
    """Reload the active Gemini Starlight CSS before showing any auth modal."""
    prepare_icon_theme()
    prefs = load_settings()
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", prefs.get("color_mode", "dark") == "dark")
    screen = Gdk.Screen.get_default()
    if screen is not None:
        for old in _THEME_PROVIDERS:
            Gtk.StyleContext.remove_provider_for_screen(screen, old)
        _THEME_PROVIDERS.clear()
        for path in (BASE / "shell/style.css", BASE / "theme/panel.css", BASE / "shell/control_center.css"):
            if not path.is_file():
                continue
            provider = Gtk.CssProvider()
            provider.load_from_path(str(path))
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            _THEME_PROVIDERS.append(provider)
    return prefs


def parse_identities(raw_identities: list[tuple[str, dict]]) -> list[dict]:
    """Resolve Polkit D-Bus identity structs into displayable entries + Polkit.Identity."""
    items: list[dict] = []
    current_uid = os.getuid()
    for kind, attrs in raw_identities:
        if kind == "unix-user" and "uid" in attrs:
            uid = int(attrs["uid"])
            try:
                pw = pwd.getpwuid(uid)
                username = pw.pw_name
                gecos = pw.pw_gecos.split(",", 1)[0].strip()
                label = f"{gecos} ({username})" if gecos and gecos != username else username
            except KeyError:
                username = f"uid:{uid}"
                label = username
            items.append({
                "kind": kind,
                "uid": uid,
                "username": username,
                "label": label,
                "identity": Polkit.UnixUser.new(uid),
            })
        elif kind == "unix-group" and "gid" in attrs:
            gid = int(attrs["gid"])
            items.append({
                "kind": kind,
                "uid": -1,
                "username": f"gid:{gid}",
                "label": f"Group {gid}",
                "identity": Polkit.UnixGroup.new(gid),
            })
    # Prefer the current desktop user first when present.
    items.sort(key=lambda item: (0 if item["uid"] == current_uid else 1, item["uid"]))
    return items


def format_passkey(passkey: int) -> str:
    """Format a 6-digit Bluetooth passkey cleanly as '123 456'."""
    digits = f"{int(passkey):06d}"
    return f"{digits[:3]} {digits[3:]}"


def _build_modal_shell(title_text: str, subtitle_text: str, *, avatar_skin: str = "obsidian",
                       namespace: str = "selandia-polkit", width: int = 440) -> tuple[Gtk.Window, Gtk.Box, Gtk.Button]:
    """Create a centered Layer-Shell frosted glass dialog matching Control Center."""
    prefs = reload_theme()
    reduced = bool(prefs.get("reduced_motion", False))
    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_title(f"Selandia · {title_text}")
    win.set_decorated(False)
    win.set_resizable(False)
    win.set_app_paintable(True)
    win.set_default_size(width, -1)
    win.set_size_request(width, -1)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)

    ctx = win.get_style_context()
    ctx.add_class("glass-window")
    ctx.add_class("polkit-window")
    if reduced:
        ctx.add_class("reduce-motion")

    if GtkLayerShell.is_supported():
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, namespace)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_exclusive_zone(win, -1)
    else:
        win.set_position(Gtk.WindowPosition.CENTER)

    surface = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "glass-surface")
    win.add(surface)

    header = pack(surface, style(Gtk.Box(spacing=12), "panel-header"))
    avatar_path = mascot_asset(avatar_skin, "avatar")
    if avatar_path.is_file():
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(avatar_path), 46, 46, True)
            frame = style(Gtk.Box(), "mascot-avatar-frame")
            frame.set_valign(Gtk.Align.CENTER)
            pack(frame, Gtk.Image.new_from_pixbuf(pix))
            pack(header, frame)
        except (GLib.Error, OSError):
            pass
    titles = pack(header, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), True)
    titles.set_valign(Gtk.Align.CENTER)
    pack(titles, style(Gtk.Label(label=title_text, xalign=0), "control-heading"))
    cap = style(Gtk.Label(label=subtitle_text, xalign=0), "control-caption")
    cap.set_ellipsize(Pango.EllipsizeMode.END)
    pack(titles, cap)

    close_btn = style(Gtk.Button(label="×"), "close-button")
    close_btn.set_valign(Gtk.Align.START)
    close_btn.set_tooltip_text(tr("Cancel · Esc", "取消 · Esc"))
    pack(header, close_btn)

    body = pack(surface, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "panel-content"))
    return win, body, close_btn


class PolkitAuthDialog:
    """Interactive Polkit PAM modal backed strictly by ``PolkitAgent.Session``."""

    def __init__(self, *, action_id: str, message: str, details: dict[str, str],
                 cookie: str, identities: list[dict], on_done, preview: bool = False):
        self.action_id = action_id
        self.cookie = cookie
        self.identities = identities
        self.on_done = on_done
        self.preview = preview
        self.session: PolkitAgent.Session | None = None
        self._finished = False
        self._authenticating = False

        self.window, body, close_btn = _build_modal_shell(
            tr("Administrator Authentication", "管理员身份验证"),
            tr("Verified by system Polkit PAM", "由系统原生 Polkit 安全校验"),
            avatar_skin="obsidian",
            namespace="selandia-polkit",
            width=456,
        )
        close_btn.connect("clicked", lambda _: self.cancel())
        self.window.connect("delete-event", lambda *_: (self.cancel(), True)[1])
        self.window.connect("key-press-event", self._on_key)

        msg_card = pack(body, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "card"))
        msg_lbl = style(Gtk.Label(label=message or tr("Authentication is required to continue.", "继续执行此系统操作需要管理员授权。"),
                                  xalign=0), "auth-message")
        msg_lbl.set_line_wrap(True)
        msg_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        msg_lbl.set_max_width_chars(46)
        pack(msg_card, msg_lbl)

        meta_parts = []
        if action_id:
            meta_parts.append(action_id)
        if details.get("polkit.gettext_domain"):
            pass
        cmd = details.get("command_line") or details.get("program") or details.get("unit")
        if cmd:
            meta_parts.append(cmd)
        if meta_parts:
            meta_lbl = style(Gtk.Label(label=" · ".join(meta_parts), xalign=0), "hint")
            meta_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            meta_lbl.set_max_width_chars(52)
            meta_lbl.set_tooltip_text("\n".join(meta_parts))
            pack(msg_card, meta_lbl)

        # Identity selector (dropdown if >1 admin, clean chip if 1)
        self.identity_combo = None
        if len(identities) > 1:
            id_row = pack(body, Gtk.Box(spacing=10))
            pack(id_row, style(Gtk.Label(label=tr("Identity", "授权账户"), xalign=0), "control-label"))
            self.identity_combo = Gtk.ComboBoxText()
            for idx, item in enumerate(identities):
                self.identity_combo.append(str(idx), item["label"])
            self.identity_combo.set_active(0)
            self.identity_combo.connect("changed", self._on_identity_changed)
            pack(id_row, self.identity_combo, True)
        elif identities:
            id_chip = pack(body, style(Gtk.Box(spacing=8), "data-row"))
            pack(id_chip, icon("avatar-default-symbolic", 16))
            pack(id_chip, style(Gtk.Label(label=identities[0]["label"], xalign=0), "control-label"), True)
            pack(id_chip, style(Gtk.Label(label=tr("Polkit", "系统鉴权")), "status-badge"))

        # Prompt + Password entry with visibility toggle
        self.prompt_label = pack(body, style(Gtk.Label(label=tr("Password", "请输入密码"), xalign=0), "auth-prompt"))
        pw_row = pack(body, Gtk.Box(spacing=8))
        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.entry.set_placeholder_text(tr("Enter password…", "输入管理员密码…"))
        self.entry.connect("activate", lambda _: self.submit())
        pack(pw_row, self.entry, True)

        self.reveal_btn = style(Gtk.ToggleButton(), "small-button")
        self.reveal_btn.set_image(icon("view-reveal-symbolic", 16))
        self.reveal_btn.set_tooltip_text(tr("Show / hide password", "显示 / 隐藏密码"))
        self.reveal_btn.connect("toggled", lambda b: self.entry.set_visibility(b.get_active()))
        pack(pw_row, self.reveal_btn)

        self.info_label = pack(body, style(Gtk.Label(label="", xalign=0), "hint"))
        self.info_label.set_line_wrap(True)
        self.info_label.set_no_show_all(True)

        self.error_label = pack(body, style(Gtk.Label(label="", xalign=0), "auth-error"))
        self.error_label.set_line_wrap(True)
        self.error_label.set_no_show_all(True)

        actions = pack(body, Gtk.Box(spacing=10))
        self.cancel_btn = pack(actions, style(Gtk.Button(label=tr("Cancel", "取消")), "text-button"), True)
        self.cancel_btn.connect("clicked", lambda _: self.cancel())
        self.auth_btn = pack(actions, style(Gtk.Button(label=tr("Authenticate", "授权验证")), "accent-button"), True)
        self.auth_btn.connect("clicked", lambda _: self.submit())

        self.window.show_all()
        self.window.present()
        GLib.idle_add(self.entry.grab_focus)

        if not self.preview:
            self._start_session()

    def _selected_identity(self):
        if not self.identities:
            return None
        if self.identity_combo is not None:
            idx = self.identity_combo.get_active()
            if 0 <= idx < len(self.identities):
                return self.identities[idx]["identity"]
        return self.identities[0]["identity"]

    def _on_identity_changed(self, *_):
        if self.preview or self._finished:
            return
        self._cancel_session_only()
        self._set_error("")
        self._set_info("")
        self.entry.set_text("")
        self._start_session()

    def _cancel_session_only(self):
        if self.session is not None:
            sess, self.session = self.session, None
            try:
                sess.cancel()
            except Exception:
                pass

    def _start_session(self):
        identity = self._selected_identity()
        if identity is None:
            self._finish(False, cancelled=False, error="No valid authentication identity")
            return
        self._authenticating = False
        sess = PolkitAgent.Session.new(identity, self.cookie)
        sess.connect("request", self._on_request)
        sess.connect("show-info", self._on_show_info)
        sess.connect("show-error", self._on_show_error)
        sess.connect("completed", self._on_completed)
        self.session = sess
        sess.initiate()

    def _on_request(self, sess, request_text, echo_on):
        if sess is not self.session or self._finished:
            return
        cleaned = (request_text or "").strip().rstrip(":")
        if cleaned.lower() == "password":
            cleaned = tr("Password", "请输入密码")
        self.prompt_label.set_text(cleaned or tr("Password", "请输入密码"))
        self.entry.set_visibility(bool(echo_on) or self.reveal_btn.get_active())
        self.entry.set_sensitive(True)
        self.auth_btn.set_sensitive(True)
        self.entry.grab_focus()

    def _on_show_info(self, sess, text):
        if sess is not self.session or self._finished:
            return
        self._set_info(text or "")

    def _on_show_error(self, sess, text):
        if sess is not self.session or self._finished:
            return
        self._set_error(text or "")

    def _on_completed(self, sess, gained_authorization):
        if sess is not self.session or self._finished:
            return
        self.session = None
        self._authenticating = False
        self.entry.set_text("")
        if gained_authorization:
            self._finish(True, cancelled=False)
        else:
            self._set_error(tr("Authentication failed. Please check your password and try again.",
                               "验证失败，请检查密码后重试。"))
            self.entry.set_sensitive(True)
            self.auth_btn.set_sensitive(True)
            self._start_session()
            self.entry.grab_focus()

    def _set_info(self, text: str):
        self.info_label.set_text(text)
        self.info_label.set_visible(bool(text))

    def _set_error(self, text: str):
        self.error_label.set_text(text)
        self.error_label.set_visible(bool(text))

    def submit(self):
        if self._finished or self._authenticating:
            return
        if self.preview:
            self.cancel()
            return
        if self.session is None:
            return
        password = self.entry.get_text()
        # Wipe entry immediately so password never lingers in UI memory.
        self.entry.set_text("")
        self._set_error("")
        self._authenticating = True
        self.entry.set_sensitive(False)
        self.auth_btn.set_sensitive(False)
        self.session.response(password)

    def _on_key(self, _win, event):
        if event.keyval == Gdk.KEY_Escape:
            self.cancel()
            return True
        return False

    def cancel(self, *, remote: bool = False):
        if self._finished:
            return
        self.entry.set_text("")
        self._cancel_session_only()
        self._finish(False, cancelled=True, remote=remote)

    def _finish(self, ok: bool, *, cancelled: bool, remote: bool = False, error: str = ""):
        if self._finished:
            return
        self._finished = True
        self.entry.set_text("")
        self.window.destroy()
        self.on_done(ok, cancelled, remote, error)


class BluezPromptDialog:
    """Gemini Starlight modal for BlueZ pairing confirmation / PIN / passkey."""

    def __init__(self, *, mode: str, device_name: str, device_addr: str,
                 passkey_text: str = "", on_result):
        self.mode = mode
        self.on_result = on_result
        self._done = False

        self.window, body, close_btn = _build_modal_shell(
            tr("Bluetooth Pairing", "蓝牙设备配对"),
            f"{device_name} · {device_addr}" if device_addr else device_name,
            avatar_skin="gemini",
            namespace="selandia-polkit",
            width=430,
        )
        close_btn.connect("clicked", lambda _: self.reject())
        self.window.connect("delete-event", lambda *_: (self.reject(), True)[1])
        self.window.connect("key-press-event", self._on_key)

        card = pack(body, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card"))
        self.entry = None
        if mode == "confirm":
            lbl = style(Gtk.Label(label=tr("Confirm that this pairing code matches the device:",
                                           "请确认对方设备上显示的配对码与下方一致："), xalign=0), "auth-message")
            lbl.set_line_wrap(True)
            pack(card, lbl)
            code = style(Gtk.Label(label=passkey_text), "auth-passkey")
            code.set_halign(Gtk.Align.CENTER)
            pack(card, code)
        elif mode in ("pin", "passkey"):
            lbl = style(Gtk.Label(label=tr("Enter the pairing PIN / passkey for this Bluetooth device:",
                                           "请输入该蓝牙设备的配对 PIN 或数字配对码："), xalign=0), "auth-message")
            lbl.set_line_wrap(True)
            pack(card, lbl)
            self.entry = Gtk.Entry()
            self.entry.set_placeholder_text("000000")
            self.entry.connect("activate", lambda _: self.accept())
            pack(card, self.entry)
        else:
            lbl = style(Gtk.Label(label=tr("Allow this Bluetooth device to connect and use services?",
                                           "是否允许此蓝牙设备建立配对与连接？"), xalign=0), "auth-message")
            lbl.set_line_wrap(True)
            pack(card, lbl)

        actions = pack(body, Gtk.Box(spacing=10))
        cancel_btn = pack(actions, style(Gtk.Button(label=tr("Reject", "拒绝")), "text-button"), True)
        cancel_btn.connect("clicked", lambda _: self.reject())
        ok_btn = pack(actions, style(Gtk.Button(label=tr("Confirm Pair", "确认配对")), "accent-button"), True)
        ok_btn.connect("clicked", lambda _: self.accept())

        self.window.show_all()
        self.window.present()
        GLib.idle_add((self.entry or ok_btn).grab_focus)

    def _on_key(self, _win, event):
        if event.keyval == Gdk.KEY_Escape:
            self.reject()
            return True
        return False

    def accept(self):
        if self._done:
            return
        value = self.entry.get_text().strip() if self.entry is not None else ""
        if self.mode == "passkey" and not value.isdigit():
            return
        if self.mode == "pin" and not value:
            return
        self._done = True
        self.window.destroy()
        self.on_result(True, value)

    def reject(self):
        if self._done:
            return
        self._done = True
        self.window.destroy()
        self.on_result(False, "")


class NativeSystemAgent:
    """Single lightweight D-Bus daemon hosting Polkit Agent + BlueZ Agent1."""

    def __init__(self, loop: GLib.MainLoop):
        self.loop = loop
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.polkit_reg_id = 0
        self.polkit_registered = False
        self.polkit_subject = None
        self.active_polkit: dict[str, PolkitAuthDialog] = {}
        self.bluez_reg_id = 0
        self.bluez_registered = False
        self.active_bluez: BluezPromptDialog | None = None

    def _resolve_session_id(self) -> str:
        try:
            subject = Polkit.UnixSession.new_for_process_sync(os.getpid(), None)
            if subject is not None:
                sid = subject.get_session_id()
                if sid:
                    return sid
        except Exception:
            pass
        env_sid = os.environ.get("XDG_SESSION_ID", "").strip()
        if env_sid:
            return env_sid
        try:
            raw = Path("/proc/self/sessionid").read_text().strip()
            if raw and raw != "4294967295":
                return raw
        except OSError:
            pass
        raise RuntimeError("Could not determine active logind session ID for Polkit registration")

    def start(self):
        self._start_polkit()
        self._start_bluez()

    def _start_polkit(self):
        node = Gio.DBusNodeInfo.new_for_xml(POLKIT_AGENT_XML)
        self.polkit_reg_id = self.bus.register_object(
            POLKIT_OBJECT_PATH,
            node.interfaces[0],
            self._on_polkit_call,
            None,
            None,
        )
        sid = self._resolve_session_id()
        self.polkit_subject = ("unix-session", {"session-id": GLib.Variant("s", sid)})
        locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en_US.UTF-8"
        self.bus.call_sync(
            "org.freedesktop.PolicyKit1",
            "/org/freedesktop/PolicyKit1/Authority",
            "org.freedesktop.PolicyKit1.Authority",
            "RegisterAuthenticationAgent",
            GLib.Variant("((sa{sv})ss)", (self.polkit_subject, locale, POLKIT_OBJECT_PATH)),
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )
        self.polkit_registered = True

    def _start_bluez(self):
        try:
            node = Gio.DBusNodeInfo.new_for_xml(BLUEZ_AGENT_XML)
            self.bluez_reg_id = self.bus.register_object(
                BLUEZ_OBJECT_PATH,
                node.interfaces[0],
                self._on_bluez_call,
                None,
                None,
            )
            self.bus.call_sync(
                "org.bluez",
                "/org/bluez",
                "org.bluez.AgentManager1",
                "RegisterAgent",
                GLib.Variant("(os)", (BLUEZ_OBJECT_PATH, "KeyboardDisplay")),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            self.bus.call_sync(
                "org.bluez",
                "/org/bluez",
                "org.bluez.AgentManager1",
                "RequestDefaultAgent",
                GLib.Variant("(o)", (BLUEZ_OBJECT_PATH,)),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            self.bluez_registered = True
        except Exception as err:
            # Bluetooth daemon may be disabled; never block Polkit agent startup.
            print(f"BlueZ agent registration skipped: {err}", file=sys.stderr, flush=True)

    def _on_polkit_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "BeginAuthentication":
            action_id, message, _icon_name, details, cookie, raw_ids = params.unpack()
            identities = parse_identities(raw_ids)
            if not identities:
                invocation.return_dbus_error("org.freedesktop.PolicyKit1.Error.Failed",
                                             "No eligible administrator identity")
                return

            def done(ok: bool, cancelled: bool, _remote: bool, error: str):
                self.active_polkit.pop(cookie, None)
                if ok:
                    invocation.return_value(None)
                elif cancelled:
                    invocation.return_dbus_error("org.freedesktop.PolicyKit1.Error.Cancelled",
                                                 "Authentication cancelled by user")
                else:
                    invocation.return_dbus_error("org.freedesktop.PolicyKit1.Error.Failed",
                                                 error or "Authentication failed")

            dialog = PolkitAuthDialog(
                action_id=action_id,
                message=message,
                details=details or {},
                cookie=cookie,
                identities=identities,
                on_done=done,
            )
            self.active_polkit[cookie] = dialog
            return

        if method == "CancelAuthentication":
            (cookie,) = params.unpack()
            dialog = self.active_polkit.get(cookie)
            if dialog is not None:
                dialog.cancel(remote=True)
            invocation.return_value(None)
            return

        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _bluez_device_info(self, device_path: str) -> tuple[str, str]:
        try:
            res = self.bus.call_sync(
                "org.bluez",
                device_path,
                "org.freedesktop.DBus.Properties",
                "GetAll",
                GLib.Variant("(s)", ("org.bluez.Device1",)),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            props = res.unpack()[0]
            return str(props.get("Alias") or props.get("Name") or device_path.rsplit("/", 1)[-1]), str(props.get("Address") or "")
        except Exception:
            return device_path.rsplit("/", 1)[-1], ""

    def _on_bluez_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Release":
            invocation.return_value(None)
            return
        if method == "Cancel":
            if self.active_bluez is not None:
                self.active_bluez.reject()
            invocation.return_value(None)
            return
        if method in ("DisplayPasskey", "DisplayPinCode"):
            args = params.unpack()
            name, _addr = self._bluez_device_info(args[0])
            code = format_passkey(args[1]) if method == "DisplayPasskey" else str(args[1])
            try:
                import subprocess
                subprocess.Popen(["notify-send", "-a", "Selandia Bluetooth",
                                  tr("Bluetooth Pairing Code", "蓝牙配对码"),
                                  f"{name}: {code}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            invocation.return_value(None)
            return

        if self.active_bluez is not None:
            self.active_bluez.reject()

        args = params.unpack()
        name, addr = self._bluez_device_info(args[0])

        if method == "RequestConfirmation":
            code = format_passkey(args[1])
            def done(ok, _val):
                self.active_bluez = None
                if ok:
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Pairing rejected")
            self.active_bluez = BluezPromptDialog(mode="confirm", device_name=name, device_addr=addr,
                                                  passkey_text=code, on_result=done)
            return

        if method == "RequestPinCode":
            def done(ok, val):
                self.active_bluez = None
                if ok and val:
                    invocation.return_value(GLib.Variant("(s)", (val,)))
                else:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "PIN entry cancelled")
            self.active_bluez = BluezPromptDialog(mode="pin", device_name=name, device_addr=addr, on_result=done)
            return

        if method == "RequestPasskey":
            def done(ok, val):
                self.active_bluez = None
                if ok and val.isdigit():
                    invocation.return_value(GLib.Variant("(u)", (int(val),)))
                else:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Passkey entry cancelled")
            self.active_bluez = BluezPromptDialog(mode="passkey", device_name=name, device_addr=addr, on_result=done)
            return

        if method in ("RequestAuthorization", "AuthorizeService"):
            def done(ok, _val):
                self.active_bluez = None
                if ok:
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error("org.bluez.Error.Rejected", "Authorization denied")
            self.active_bluez = BluezPromptDialog(mode="authorize", device_name=name, device_addr=addr, on_result=done)
            return

        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def stop(self):
        for dialog in list(self.active_polkit.values()):
            dialog.cancel(remote=True)
        if self.active_bluez is not None:
            self.active_bluez.reject()
        if self.polkit_registered and self.polkit_subject is not None:
            try:
                self.bus.call_sync(
                    "org.freedesktop.PolicyKit1",
                    "/org/freedesktop/PolicyKit1/Authority",
                    "org.freedesktop.PolicyKit1.Authority",
                    "UnregisterAuthenticationAgent",
                    GLib.Variant("((sa{sv})s)", (self.polkit_subject, POLKIT_OBJECT_PATH)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    3000,
                    None,
                )
            except Exception:
                pass
            self.polkit_registered = False
        if self.polkit_reg_id:
            self.bus.unregister_object(self.polkit_reg_id)
            self.polkit_reg_id = 0
        if self.bluez_registered:
            try:
                self.bus.call_sync(
                    "org.bluez",
                    "/org/bluez",
                    "org.bluez.AgentManager1",
                    "UnregisterAgent",
                    GLib.Variant("(o)", (BLUEZ_OBJECT_PATH,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    2000,
                    None,
                )
            except Exception:
                pass
            self.bluez_registered = False
        if self.bluez_reg_id:
            self.bus.unregister_object(self.bluez_reg_id)
            self.bluez_reg_id = 0


def run_preview():
    """Render a safe local preview dialog (no D-Bus registration or PAM session)."""
    if not Gtk.init_check()[0]:
        return 1
    loop = GLib.MainLoop()
    user = pwd.getpwuid(os.getuid())
    PolkitAuthDialog(
        action_id="org.freedesktop.policykit.exec",
        message=tr("Authentication is required to run `/usr/bin/ufw status verbose` as the super user.",
                   "需要管理员授权才能运行系统防火墙配置（/usr/bin/ufw）。"),
        details={"command_line": "/usr/bin/ufw status verbose"},
        cookie="preview",
        identities=[{"kind": "unix-user", "uid": os.getuid(), "username": user.pw_name,
                     "label": user.pw_name, "identity": None}],
        on_done=lambda *_: loop.quit(),
        preview=True,
    )
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *_: (loop.quit(), False)[1])
    loop.run()
    return 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--preview"]:
        return run_preview()
    if args:
        print("Usage: polkit_agent.py [--preview]", file=sys.stderr)
        return 2
    if not Gtk.init_check()[0]:
        print("Wayland display required for Selandia Polkit Agent", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    agent = NativeSystemAgent(loop)
    try:
        agent.start()
    except Exception as err:
        print(f"Failed to register native Polkit agent: {err}", file=sys.stderr, flush=True)
        agent.stop()
        return 1

    def shutdown(*_):
        agent.stop()
        loop.quit()
        return GLib.SOURCE_REMOVE

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_args: GLib.idle_add(shutdown))

    try:
        loop.run()
    finally:
        agent.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
