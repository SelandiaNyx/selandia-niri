"""Live application streams; polling preserves widgets, drags and mixer changes."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango
import audio_backend
from control_widgets import pack, style
from i18n import tr
from system_controls import text


class ApplicationAudioControls(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.panel = panel
        self.entries = {}
        style(self, "card")
        style(self, "application-audio")
        pack(self, text(tr("Application volume", "应用音量"), "section-title"))
        self.notice = pack(self, text(tr("Reading playback and recording streams…", "正在读取播放与录音应用…"), "hint"))
        self.rows = pack(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10))
        self.connect("destroy", self.cleanup)

    def cleanup(self, *_):
        for row in self.entries.values():
            self.cancel_timer(row)

    def cancel_timer(self, row):
        source = row.pop("timer", None)
        if source is not None:
            if source in self.panel.pending:
                GLib.source_remove(source)
            self.panel.pending.discard(source)

    def update(self, streams, errors=()):
        keys = set()
        for stream in streams:
            key = (stream["kind"], stream["index"], tuple(stream["identity"]))
            keys.add(key)
            if key not in self.entries:
                self.entries[key] = self.add_row(key, stream)
            row = self.entries[key]
            row["stream"] = dict(stream)
            row["updating"] = True
            direction = tr("Playback", "播放") if stream["kind"] == "sink-input" else tr("Recording", "录音")
            row["title"].set_text(stream["name"])
            row["subtitle"].set_text(direction + (" · " + stream["media"] if stream["media"] else ""))
            row["widget"].set_tooltip_text(f"{stream['name']} · {direction} · #{stream['index']}")
            if not row["dragging"] and not row["busy"] and not row["pending"]:
                volume = stream["volume"]
                row["value"].set_text(tr("Unavailable", "不可用") if volume is None else f"{volume:.0f}%")
                if volume is not None:
                    row["scale"].set_value(min(100, volume))
                row["mute"].set_active(stream["mute"] is True)
            row["scale"].set_sensitive(stream["volume"] is not None and stream["volume_writable"])
            row["mute"].set_sensitive(stream["mute"] is not None)
            row["updating"] = False
        for key in list(self.entries):
            if key not in keys:
                row = self.entries.pop(key)
                self.cancel_timer(row)
                row["widget"].destroy()
        self.notice.set_text("\n".join(errors) if errors else (tr("Playback and recording adjust independently; changes apply immediately.",
                             "播放与录音分别调节，修改实时生效。") if keys else tr("No active application audio streams.", "当前没有应用音频流。")))
        self.rows.show_all()

    def add_row(self, key, stream):
        widget = pack(self.rows, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        style(widget, "audio-stream-row")
        title = pack(widget, text(stream["name"]))
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(36)
        subtitle = pack(widget, text("", "hint"))
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_max_width_chars(42)
        controls = pack(widget, Gtk.Box(spacing=8))
        scale = pack(controls, Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1), True)
        scale.set_draw_value(False)
        value = pack(controls, text("", "value"))
        mute = pack(controls, Gtk.ToggleButton(label=tr("Mute", "静音")))
        row = dict(widget=widget, title=title, subtitle=subtitle, scale=scale, value=value, mute=mute,
                   stream=dict(stream), busy=False, updating=False, dragging=False, pending={})
        scale.connect("value-changed", lambda *_: self.change(key, volume=round(scale.get_value())))
        scale.connect("button-press-event", lambda *_: row.update(dragging=True) or False)
        scale.connect("button-release-event", lambda *_: row.update(dragging=False) or False)
        scale.connect("focus-out-event", lambda *_: row.update(dragging=False) or False)
        mute.connect("toggled", lambda *_: self.change(key, muted=mute.get_active()))
        self.panel.protect_scroll_controls(widget)
        return row

    def change(self, key, **values):
        row = self.entries.get(key)
        if row is None or row["updating"]:
            return
        row["pending"].update(values)
        if "volume" in values:
            row["value"].set_text(f"{values['volume']}%")
        self.cancel_timer(row)
        def dispatch():
            source = row.pop("timer", None)
            self.panel.pending.discard(source)
            self.flush(key)
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(100 if "volume" in values else 1, dispatch)
        row["timer"] = source
        self.panel.pending.add(source)

    def flush(self, key):
        row = self.entries.get(key)
        if row is None or row["busy"] or not row["pending"]:
            return
        values, row["pending"] = row["pending"], {}
        stream = dict(row["stream"])
        row["busy"] = True
        def finish(error=None):
            row["busy"] = False
            if error:
                row["pending"].clear()
                self.panel.feedback(str(error), True)
            if self.entries.get(key) is row:
                self.flush(key)
            self.panel.refresh_audio()
        self.panel.work(lambda: audio_backend.set_stream_audio(stream, **values), lambda _: finish(), finish, commit=True)
