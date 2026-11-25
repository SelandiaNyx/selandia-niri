"""Player-specific media controls; pause never depends on playlist navigation."""
from pathlib import Path
import threading
from urllib.parse import unquote, urlparse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from control_widgets import icon, icon_button, pack, style, text
import media_backend as backend
from media_events import MediaChanges
from i18n import tr, tr_legacy


def local_cover(uri):
    """Use artwork already supplied locally by the player; no network fetches."""
    parsed = urlparse(uri or "")
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    path = Path(unquote(parsed.path))
    try:
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            return None
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 48, 48, True)
    except (OSError, GLib.Error):
        return None


class MediaControls(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        style(self, "media-card")
        self.panel = panel
        self.preferred = None
        self.selected = None
        self.loading = False
        self.busy = False
        self.guard = False
        self.generation = 0
        self.art_uri = None
        self.art_pending = None
        self.source = style(Gtk.ComboBoxText(), "media-source")
        for cell in self.source.get_cells():
            cell.set_property("max-width-chars", 16)
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.source.get_accessible().set_name(tr("Media source", "播放来源"))
        self.source.set_tooltip_text(tr("Choose the player to control", "选择要控制的播放器"))
        self.source.connect("changed", self.source_changed)
        pack(self, self.source)
        info = pack(self, Gtk.Box(spacing=9))
        cover = style(Gtk.Box(), "media-cover")
        cover.set_size_request(48, 48)
        cover.set_valign(Gtk.Align.CENTER)
        self.art = icon("audio-x-generic-symbolic", 28)
        self.art.set_halign(Gtk.Align.CENTER)
        self.art.set_valign(Gtk.Align.CENTER)
        pack(cover, self.art, True)
        pack(info, cover)
        metadata = pack(info, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3), True)
        metadata.set_valign(Gtk.Align.CENTER)
        self.title = pack(metadata, text(tr("Not playing", "没有正在播放的音乐"), "media-heading", 22))
        self.artist = pack(metadata, text(tr("Open a player to listen", "打开播放器开始聆听"), "media-subtitle", 24))
        self.status = pack(metadata, text(tr("Not playing", "未播放"), "media-state", 24))
        transport = pack(self, Gtk.Box(spacing=8))
        transport.set_halign(Gtk.Align.CENTER)
        self.buttons = {}
        for action, image, title in [("previous", "media-skip-backward-symbolic", tr("Previous", "上一首")),
                                      ("toggle", "media-playback-start-symbolic", tr("Play", "播放")),
                                      ("next", "media-skip-forward-symbolic", tr("Next", "下一首"))]:
            button, image_widget = icon_button(image, title, lambda a=action: self.perform(a),
                                               "media-play" if action == "toggle" else "media-transport")
            button.set_sensitive(False)
            pack(transport, button)
            self.buttons[action] = button
            if action == "toggle":
                self.play_icon = image_widget
        self.error = pack(self, text("", "media-error", 24))
        self.error.set_no_show_all(True)
        self.source.set_sensitive(False)
        self.timer_source = None
        self.media_changes = None
        self.change_lock = threading.Lock()
        self.change_epoch = 0
        self.change_scheduled = False
        self.connect("destroy", lambda *_: self.dispose())

    def start(self):
        """Subscribe while visible; a thirty-second read repairs missed signals."""
        if self.media_changes is None and self.panel.alive:
            with self.change_lock:
                self.change_epoch += 1
                epoch = self.change_epoch
            # This card renders metadata/capabilities, not position. Players
            # emitting frequent progress signals must not cause full snapshots.
            changes = MediaChanges(threading.Event(), on_change=lambda: self.schedule_change(epoch),
                player_properties=('Metadata', 'PlaybackStatus', 'CanControl', 'CanPlay',
                                   'CanPause', 'CanGoNext', 'CanGoPrevious'),
                watch_seek=False, initial_notify=False)
            self.media_changes = changes
            changes.thread.start()
        if self.timer_source is None and self.panel.alive:
            self.timer_source = GLib.timeout_add_seconds(30, self.refresh)
            self.panel.pending.add(self.timer_source)

    def schedule_change(self, epoch):
        """Coalesce a burst on the subscriber thread before entering GTK."""
        with self.change_lock:
            if epoch != self.change_epoch or self.change_scheduled or self.media_changes is None:
                return
            self.change_scheduled = True
        GLib.timeout_add(200, self.dispatch_change, epoch)

    def dispatch_change(self, epoch):
        with self.change_lock:
            if epoch != self.change_epoch:
                return GLib.SOURCE_REMOVE
            self.change_scheduled = False
        changes = self.media_changes
        if changes is not None and changes.changed.is_set():
            self.refresh()
        return GLib.SOURCE_REMOVE

    def suspend(self):
        with self.change_lock:
            self.change_epoch += 1
            self.change_scheduled = False
        changes, self.media_changes = self.media_changes, None
        if changes is not None:
            changes.close()
            if changes.thread.ident is not None:
                self.panel.work(lambda: changes.thread.join(3), commit=True)
        source = self.timer_source
        self.timer_source = None
        if source is not None:
            self.panel.pending.discard(source)
            GLib.source_remove(source)

    def resume(self):
        if not self.panel.alive:
            return
        self.start()
        self.show_player()
        self.refresh()

    def dispose(self):
        self.suspend()

    def refresh(self):
        if not self.panel.alive:
            return GLib.SOURCE_REMOVE
        if not self.panel.page_visible('quick'):
            return GLib.SOURCE_CONTINUE
        if self.loading or self.busy:
            return GLib.SOURCE_CONTINUE
        self.loading = True
        changes = getattr(self, 'media_changes', None)
        if changes is not None:
            changes.changed.clear()
        preferred = self.preferred
        generation = self.generation

        def done(state):
            self.loading = False
            if generation != self.generation or preferred != self.preferred or self.busy:
                self.refresh()
                return
            self.apply_state(state)
            current = getattr(self, 'media_changes', None)
            if current is not None and current.changed.is_set():
                self.schedule_change(self.change_epoch)

        def failed(error):
            self.loading = False
            self.show_error(error)
            current = getattr(self, 'media_changes', None)
            if current is not None and current.changed.is_set():
                self.schedule_change(self.change_epoch)
        self.panel.work(lambda: backend.read_state(preferred), done, failed)
        return GLib.SOURCE_CONTINUE

    def apply_state(self, state):
        self.guard = True
        players = state.get("players", [])
        self.selected = state.get("selected")
        ids = {player["id"] for player in players}
        if self.preferred not in ids:
            self.preferred = None
        identity = self.selected.get("identity", "") if self.selected else ""
        rows = [("__auto__", tr(f"Automatic · {identity}", f"自动 · {identity}") if identity else tr("Media", "音乐"))]
        rows.extend((player["id"], player["identity"]) for player in players)
        # Polling must not rebuild a menu while the user is choosing a player.
        # Keep metadata verbatim; artist names and track titles are not UI text.
        if not self.source.get_property("popup-shown"):
            if rows != getattr(self, "source_rows", None):
                self.source.remove_all()
                for key, title in rows:
                    self.source.append(key, title)
                self.source_rows = rows
            self.source.set_active_id(self.preferred or "__auto__")
        self.source.set_sensitive(bool(players) and not self.busy)
        self.guard = False
        self.show_player()

    def show_player(self):
        player = self.selected or {}
        active = bool(player)
        playing = player.get("status") == "Playing"
        self.title.set_text(player.get("title") or (player.get("identity") if active else tr("Not playing", "没有正在播放的音乐")))
        artist = player.get("artist") or player.get("album") or (tr("Media player", "媒体播放器") if active else tr("Open a player to listen", "打开播放器开始聆听"))
        self.artist.set_text(artist)
        self.title.set_tooltip_text(player.get("title") or None)
        self.artist.set_tooltip_text(artist)
        self.status.set_text({"Playing": tr("Playing", "正在播放"), "Paused": tr("Paused", "已暂停"), "Stopped": tr("Stopped", "已停止")}.get(player.get("status"), tr("Not playing", "未播放")))
        if player.get("action_pending"):
            self.status.set_text(tr("Waiting for player…", "等待播放器响应…"))
        context = self.get_style_context()
        (context.add_class if playing else context.remove_class)("playing")
        self.play_icon.set_from_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.play_icon.set_pixel_size(24)
        toggle_name = tr("Pause", "暂停") if playing else tr("Play", "播放")
        self.buttons["toggle"].set_tooltip_text(toggle_name)
        self.buttons["toggle"].get_accessible().set_name(toggle_name)
        for key, capability in (("previous", "can_previous"), ("next", "can_next"),
                                ("toggle", "can_pause" if playing else "can_play")):
            self.buttons[key].set_sensitive(bool(player.get("can_control") and player.get(capability)) and not self.busy)
        uri = player.get("art_url") or ""
        if uri != self.art_uri:
            self.art_uri = uri
            self.art_pending = uri or None
            self.art.set_from_icon_name("audio-x-generic-symbolic", Gtk.IconSize.DIALOG)
            self.art.set_pixel_size(28)
        if uri and self.art_pending == uri:
            if not self.panel.page_visible("quick"):
                return
            self.art_pending = None
            def show_art(pixbuf):
                if uri == self.art_uri and pixbuf:
                    self.art.set_from_pixbuf(pixbuf)
            self.panel.work(lambda: local_cover(uri), show_art)

    def source_changed(self, combo):
        if self.guard or self.busy:
            return
        choice = combo.get_active_id()
        self.preferred = None if choice == "__auto__" else choice
        self.generation += 1
        self.selected = None
        self.show_player()
        self.error.hide()
        self.refresh()

    def show_error(self, message):
        self.error.set_text(tr("Could not control player", "播放控制失败"))
        self.error.set_tooltip_text(tr_legacy(message))
        self.error.show()
        self.panel.feedback(message, True)

    def perform(self, action):
        if self.busy or not self.selected:
            return
        if action == "toggle":
            action = "pause" if self.selected["status"] == "Playing" else "play"
        identifier = self.selected["id"]
        self.generation += 1
        self.busy = True
        self.source.set_sensitive(False)
        self.error.hide()
        self.show_player()

        def done(player):
            self.busy = False
            if self.selected and self.selected["id"] == identifier:
                self.selected = player
            self.show_player()
            self.source.set_sensitive(True)
            self.refresh()

        def failed(error):
            self.busy = False
            self.source.set_sensitive(True)
            self.show_player()
            self.show_error(error)
            self.refresh()
        self.panel.work(lambda: backend.action(identifier, action), done, failed, commit=True)
