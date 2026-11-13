"""Observe accepted notifications and SwayNC policy without owning either name."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import queue
import threading
import time

from gi.repository import Gio, GLib
from notification_policy import Policy
from notification_rules import Rules

BUS = 'org.freedesktop.DBus'
BUS_PATH = '/org/freedesktop/DBus'
NOTIFY = 'org.freedesktop.Notifications'
NOTIFY_PATH = '/org/freedesktop/Notifications'
CC = 'org.erikreider.swaync.cc'
CC_PATH = '/org/erikreider/swaync/cc'
RULES = [
    f"type='method_call',interface='{NOTIFY}',member='Notify',path='{NOTIFY_PATH}'",
    *[f"type='method_call',interface='{CC}',member='{method}',path='{CC_PATH}'"
      for method in ('ReloadConfig', 'ChangeConfigValue')],
    f"type='method_return',sender='{NOTIFY}'",
    f"type='error',sender='{NOTIFY}'",
    f"type='signal',sender='{NOTIFY}',interface='{NOTIFY}',member='NotificationClosed',path='{NOTIFY_PATH}'",
    f"type='signal',sender='{CC}',interface='{CC}',member='SubscribeV2',path='{CC_PATH}'",
    *[f"type='signal',sender='{BUS}',interface='{BUS}',member='NameOwnerChanged',arg0='{name}'"
      for name in (NOTIFY, CC)],
]


def urgency_from_hints(hints):
    """Mirror SwayNC's absent hint default and explicit byte conversion."""
    value = hints.lookup_value('urgency', None)
    if value is None or value.get_type_string() != 'y':
        return 0
    urgency = value.unpack()
    return urgency if urgency in (0, 1, 2) else 1


def read_config(path):
    """Use JSON-GLib like SwayNC, including its support for comments."""
    import gi
    gi.require_version('Json', '1.0')
    from gi.repository import Json
    try:
        parser = Json.Parser.new()
        parser.load_from_file(str(path))
        value = json.loads(Json.to_string(parser.get_root(), False))
        return value if isinstance(value, dict) else {}
    except (GLib.Error, OSError, ValueError, TypeError):
        return {}


def timeouts(config):
    # Invalid/missing config makes SwayNC use these upstream defaults.
    result = {}
    for key, default in (('timeout', 10), ('timeout-low', 5), ('timeout-critical', 0)):
        value = config.get(key, default)
        result[key] = value if type(value) is int and value >= 0 else default
    return result


class NotificationFeed:
    def __init__(self, events, stopping, *, base, address=None):
        self.events, self.stopping, self.base = events, stopping, Path(base)
        self.address = address or os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
        self.closed = threading.Event()
        self.cancellable = Gio.Cancellable()
        self.connected = False
        self.connection = None
        self.thread = threading.Thread(target=self.run, name='notification-events', daemon=True)
        self.last_state = None

    def done(self):
        return self.stopping.is_set() or self.closed.is_set()

    def close(self):
        self.closed.set()
        self.cancellable.cancel()

    def state(self, policy, **values):
        policy.update(**values)
        state = (policy.available, policy.dnd, policy.cc_open, policy.inhibited)
        if state != self.last_state:
            self.last_state = state
            self.events.put({'action': 'notification-policy', 'values': dict(zip(
                ('notifications_available', 'notification_dnd', 'notification_center_open', 'notification_inhibited'), state))})

    def connect(self):
        connection = Gio.DBusConnection.new_for_address_sync(self.address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, self.cancellable)
        connection.set_exit_on_close(False)
        return connection

    def call(self, connection, destination, path, interface, method, parameters=None):
        return connection.call_sync(destination, path, interface, method, parameters, None,
            Gio.DBusCallFlags.NO_AUTO_START, 1000, self.cancellable).unpack()

    def config_path(self, connection, owner):
        """Read the owning daemon's explicit config, never another service's args."""
        fallback = self.base / 'theme/swaync.json'
        if not fallback.exists(): fallback = self.base / 'swaync/config.json'
        try:
            pid = self.call(connection, BUS, BUS_PATH, BUS, 'GetConnectionUnixProcessID',
                            GLib.Variant('(s)', (owner,)))[0]
            process = Path('/proc') / str(pid)
            arguments = [os.fsdecode(arg) for arg in (process/'cmdline').read_bytes().split(b'\0') if arg]
            if not arguments or Path(arguments[0]).name != 'swaync': return fallback
            candidate = None
            for index, argument in enumerate(arguments[1:], 1):
                if argument in ('-c', '--config') and index+1 < len(arguments): candidate = arguments[index+1]
                elif argument.startswith('--config='): candidate = argument.partition('=')[2]
            if candidate:
                path = Path(candidate)
                if not path.is_absolute(): path = (process/'cwd').resolve()/path
                if path.is_file(): return path
            for path in (Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'swaync/config.json',
                         Path('/etc/xdg/swaync/config.json')):
                if path.is_file(): return path
        except (GLib.Error, OSError, ValueError, IndexError):
            pass
        return fallback

    def run(self):
        delay = 1
        while not self.done():
            monitor = control = None
            policy = Policy(self.events.put)
            self.state(policy, available=False)
            try:
                inbox = queue.Queue(maxsize=256)
                overflow = threading.Event()
                control = self.connect()
                monitor = self.connect()
                self.connection = monitor
                def capture(_connection, message, incoming, _data, inbox=inbox, overflow=overflow):
                    if incoming:
                        try: inbox.put_nowait(message)
                        except queue.Full: overflow.set()
                    # Monitor copies of calls must not receive GDBus error replies.
                    if incoming and message.get_message_type() == Gio.DBusMessageType.METHOD_CALL:
                        return None
                    return message
                monitor.add_filter(capture, None)
                self.call(monitor, BUS, BUS_PATH, BUS + '.Monitoring', 'BecomeMonitor',
                          GLib.Variant('(asu)', (RULES, 0)))
                owners = {}
                for name in (NOTIFY, CC):
                    try:
                        owners[name] = self.call(control, BUS, BUS_PATH, BUS, 'GetNameOwner',
                                                  GLib.Variant('(s)', (name,)))[0]
                    except GLib.Error:
                        owners[name] = ''
                pending, closed_ids, changes = OrderedDict(), OrderedDict(), OrderedDict()
                config_owner = None
                rules = Rules({})
                refresh_at = 0
                connected_at = time.monotonic()
                self.connected = True
                while not self.done() and not monitor.is_closed() and not control.is_closed():
                    if overflow.is_set():
                        raise RuntimeError('Notification event queue overflow; resynchronizing')
                    now = time.monotonic()
                    if now >= refresh_at:
                        refresh_at = float('inf')
                        if owners[CC] and owners[CC] == owners[NOTIFY]:
                            try:
                                if config_owner != owners[CC]:
                                    config = read_config(self.config_path(control, owners[CC]))
                                    rules = Rules(config); policy.configure(timeouts(config))
                                    config_owner = owners[CC]
                                dnd, cc_open, _count, inhibited = self.call(control, owners[CC], CC_PATH, CC, 'GetSubscribeData')[0]
                                self.state(policy, available=True, dnd=dnd, cc_open=cc_open, inhibited=inhibited)
                            except (GLib.Error, ValueError, TypeError):
                                self.state(policy, available=False)
                                refresh_at = now + 1
                        else:
                            self.state(policy, available=False)
                    while pending and next(iter(pending.values()))[0] < now - 10:
                        pending.popitem(last=False)
                    while changes and next(iter(changes.values()))[0] < now - 10:
                        changes.popitem(last=False)
                    try: message = inbox.get(timeout=.5)
                    except queue.Empty: continue
                    body = message.get_body()
                    if body is None: body = GLib.Variant('()', ())
                    sender, member, interface = message.get_sender(), message.get_member(), message.get_interface()
                    kind = message.get_message_type()
                    if (kind == Gio.DBusMessageType.SIGNAL and sender == BUS and interface == BUS
                            and member == 'NameOwnerChanged' and body.get_type_string() == '(sss)'):
                        name, _old, new = body.unpack()
                        if name in owners and owners[name] != new:
                            owners[name] = new; pending.clear(); closed_ids.clear(); changes.clear(); config_owner = None
                            self.state(policy, available=False)
                            refresh_at = 0
                    elif (kind == Gio.DBusMessageType.SIGNAL and sender == owners[CC] and interface == CC
                            and member == 'SubscribeV2' and body.get_type_string() == '(ubbb)'):
                        _count, dnd, cc_open, inhibited = body.unpack()
                        self.state(policy, available=bool(owners[CC] and owners[CC] == owners[NOTIFY]),
                                   dnd=dnd, cc_open=cc_open, inhibited=inhibited)
                    elif (kind == Gio.DBusMessageType.SIGNAL and sender == owners[NOTIFY] and interface == NOTIFY
                            and member == 'NotificationClosed' and body.get_type_string() == '(uu)'):
                        identifier, _reason = body.unpack()
                        policy.closed(identifier)
                        closed_ids[identifier] = time.monotonic()
                        if len(closed_ids) > 128: closed_ids.popitem(last=False)
                    elif (kind == Gio.DBusMessageType.METHOD_CALL and interface == NOTIFY and member == 'Notify'
                            and message.get_destination() in (NOTIFY, owners[NOTIFY])
                            and body.get_type_string() == '(susssasa{sv}i)'):
                        # Do not unpack image-data or action arrays merely to show
                        # a short text preview: those hints can be several MB.
                        hints = body.get_child_value(6)
                        wanted = {}
                        for name, types in (('urgency', ('y',)), ('SWAYNC_BYPASS_DND', ('b','i')),
                                            *[(key, ('s',)) for key in ('desktop-entry','category','sound-name','sound-file')]):
                            value = hints.lookup_value(name, None)
                            if value is not None and value.get_type_string() in types:
                                wanted[name] = value.unpack()
                        data = (body.get_child_value(0).unpack(), body.get_child_value(1).unpack(),
                            body.get_child_value(2).unpack()[:100], body.get_child_value(3).unpack(),
                            body.get_child_value(4).unpack(), [], wanted, body.get_child_value(7).unpack())
                        urgency = urgency_from_hints(hints)
                        visible, wanted['urgency'] = rules.decide(data, urgency)
                        # Match complete text, then retain only the bounded preview.
                        preview_hints = {name:wanted[name] for name in ('urgency','SWAYNC_BYPASS_DND') if name in wanted}
                        data = ('', data[1], data[2], data[3][:160], data[4][:320], [], preview_hints, data[7])
                        record_info = {
                            'app_name': body.get_child_value(0).unpack(),
                            'summary': body.get_child_value(3).unpack(),
                            'body': body.get_child_value(4).unpack(),
                            'icon': body.get_child_value(2).unpack()[:100],
                            'urgency': urgency,
                            'category': wanted.get('category', ''),
                        }
                        pending[(sender, message.get_serial())] = (time.monotonic(), data, visible, record_info)
                        if len(pending) > 128: pending.popitem(last=False)
                    elif (kind == Gio.DBusMessageType.METHOD_CALL and interface == CC and
                            message.get_destination() in (CC, owners[CC]) and
                            ((member == 'ReloadConfig' and body.get_type_string() == '()') or
                             (member == 'ChangeConfigValue' and body.get_type_string() == '(svbs)'))):
                        config = read_config(self.config_path(control, owners[CC]))
                        if member == 'ChangeConfigValue':
                            name = body.get_child_value(0).unpack()
                            value = body.get_child_value(1).get_variant()
                            if value.get_type_string() in ('s','i','b'): config[name] = value.unpack()
                        changes[(sender, message.get_serial())] = (time.monotonic(), config)
                        if len(changes) > 128: changes.popitem(last=False)
                    elif kind in (Gio.DBusMessageType.METHOD_RETURN, Gio.DBusMessageType.ERROR) and sender == owners[NOTIFY]:
                        change = changes.pop((message.get_destination(), message.get_reply_serial()), None)
                        if change and kind == Gio.DBusMessageType.METHOD_RETURN:
                            rules = Rules(change[1]); policy.configure(timeouts(change[1]))
                        entry = pending.pop((message.get_destination(), message.get_reply_serial()), None)
                        if entry and kind == Gio.DBusMessageType.METHOD_RETURN and body.get_type_string() == '(u)':
                            identifier = body.unpack()[0]
                            if closed_ids.get(identifier, 0) < entry[0]:
                                policy.notify(identifier, entry[1], visible=entry[2])
                                if len(entry) > 3 and isinstance(entry[3], dict):
                                    try:
                                        import notification_history
                                        rec = dict(entry[3])
                                        rec['id'] = identifier
                                        notification_history.record_notification(rec)
                                    except Exception:
                                        pass
                if time.monotonic() - connected_at > 5:
                    delay = 1
            except (GLib.Error, OSError, ValueError, KeyError, RuntimeError):
                pass
            finally:
                self.connected = False
                self.connection = None
                self.state(policy, available=False)
                for connection in (monitor, control):
                    if connection and not connection.is_closed():
                        try: connection.close_sync(None)
                        except GLib.Error: pass
            deadline = time.monotonic() + delay
            while not self.done() and time.monotonic() < deadline:
                self.closed.wait(min(.2, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, 10)
