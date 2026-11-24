"""Arch Package Maintenance (pacman/paru), Desktop Diagnostics & Docker Control."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from control_widgets import (
    card_grid,
    data_row,
    grid_add,
    inline_confirm_bar,
    nyx_guide_banner,
    pack,
    status_badge,
    style,
    wrap_label,
)
from i18n import tr
from metrics import format_bytes
import package_docker_backend as backend


class PackagesPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False

        pack(self, nyx_guide_banner(
            "packages",
            tr("Inspect Arch packages, orphans and pacman cache size, run safe maintenance, and control Docker containers.",
               "一站式查看 Arch 软件包、孤立包与缓存体积、执行安全维护与自检，并直接启停管理 Docker 容器。"),
            skin="engineer",
        ))

        self.notice = pack(self, wrap_label("", "hint"))
        self.notice.set_no_show_all(True)
        self.confirm_slot = pack(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.confirm_slot.set_no_show_all(True)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self, card_grid(wide, 12))

        # Left column: Arch Packages & Desktop Maintenance
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        pkg_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        phdr = pack(pkg_card, Gtk.Box(spacing=8))
        pack(phdr, wrap_label(tr("ARCH PACKAGES & CACHE", "ARCH 软件包与缓存"), "section-title"), True)
        self.check_btn = style(Gtk.Button(label=tr("Check updates", "检查更新")), "accent-button")
        self.check_btn.connect("clicked", lambda _: self.refresh(check_updates=True))
        pack(phdr, self.check_btn)

        self.pkg_stats = pack(pkg_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))

        pkg_actions = pack(pkg_card, Gtk.Box(spacing=8))
        up_btn = style(Gtk.Button(label=tr("Full upgrade (terminal)", "终端完整升级")), "small-button")
        up_btn.connect("clicked", lambda _: self.panel.launch_external([self.panel.desktop_script(), "updates"]))
        self.clean_btn = style(Gtk.Button(label=tr("Clean cache…", "清理包缓存…")), "small-button")
        self.clean_btn.connect("clicked", lambda _: self._ask_clean_cache())
        pack(pkg_actions, up_btn, True)
        pack(pkg_actions, self.clean_btn, True)

        self.updates_box = pack(pkg_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4))
        pack(left, pkg_card)

        maint_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(maint_card, wrap_label(tr("DESKTOP MAINTENANCE", "桌面维护与自检"), "section-title"))
        mgrid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        for idx, (lbl, act) in enumerate((
            (tr("Repair desktop", "修复桌面部署"), "repair"),
            (tr("Install status", "检查安装状态"), "status"),
            (tr("Full diagnostics", "运行完整自检"), "check"),
            (tr("Open terminal", "打开终端"), "terminal"),
        )):
            btn = style(Gtk.Button(label=lbl), "small-button")
            if act == "terminal":
                btn.connect("clicked", lambda _: self.panel.launch_external([self.panel.desktop_script(), "launch", "terminal"]))
            else:
                btn.connect("clicked", lambda _b, a=act: self.panel.launch_external([self.panel.desktop_script(), a]))
            mgrid.attach(btn, idx % 2, idx // 2, 1, 1)
        pack(maint_card, mgrid)
        pack(left, maint_card)
        grid_add(grid, left)

        # Right column: Docker Containers
        docker_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        dhdr = pack(docker_card, Gtk.Box(spacing=8))
        pack(dhdr, wrap_label(tr("DOCKER CONTAINERS", "DOCKER 容器管理"), "section-title"), True)
        dref = style(Gtk.Button(label=tr("Refresh", "刷新")), "small-button")
        dref.connect("clicked", lambda _: self.refresh(check_updates=False))
        pack(dhdr, dref)
        self.docker_box = pack(docker_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, docker_card)

    def _set_notice(self, message: str):
        self.notice.set_text(message)
        self.notice.set_visible(bool(message))

    def _clear_confirm(self):
        for child in self.confirm_slot.get_children():
            child.destroy()
        self.confirm_slot.hide()

    def refresh(self, *, check_updates: bool = False):
        if self.busy:
            return
        self.busy = True
        self.check_btn.set_sensitive(False)
        self._set_notice(tr("Checking Arch updates and Docker…", "正在检查软件包更新与 Docker 状态…")
                         if check_updates else tr("Reading packages and containers…", "正在读取软件包与容器状态…"))

        def read():
            return backend.read_package_state(check_updates=check_updates), backend.read_docker_state()

        self.panel.work(read, self._render, self._failed)

    def _failed(self, err):
        self.busy = False
        self.check_btn.set_sensitive(True)
        self._set_notice(str(err))

    def _render(self, payload):
        pkg, dk = payload
        self.busy = False
        self.check_btn.set_sensitive(True)
        self._set_notice("")

        for container in (self.pkg_stats, self.updates_box, self.docker_box):
            for child in container.get_children():
                child.destroy()

        pack(self.pkg_stats, data_row(
            wrap_label(tr("Installed packages", "已安装软件包"), "control-label"),
            status_badge(str(pkg["installed_count"]), "info"),
        ))
        orphan_count = len(pkg["orphans"])
        pack(self.pkg_stats, data_row(
            wrap_label(tr("Orphan packages", "孤立依赖包"), "control-label"),
            status_badge(str(orphan_count), "warn" if orphan_count else "ok"),
        ))
        cache_lbl = f"{format_bytes(pkg['cache_bytes'])} ({pkg['cache_files']})"
        pack(self.pkg_stats, data_row(
            wrap_label(tr("Pacman package cache", "Pacman 包缓存体积"), "control-label"),
            status_badge(cache_lbl, "warn" if pkg["cache_bytes"] > 1024**3 else "info"),
        ))

        if pkg["updates_checked"]:
            total = len(pkg["updates"]) + len(pkg["aur_updates"])
            if total == 0:
                pack(self.updates_box, wrap_label(tr("System is up to date.", "所有软件包均为最新。"), "hint"))
            else:
                pack(self.updates_box, wrap_label(
                    tr(f"{len(pkg['updates'])} official + {len(pkg['aur_updates'])} AUR updates available:",
                       f"发现 {len(pkg['updates'])} 个官方源更新 + {len(pkg['aur_updates'])} 个 AUR 更新："),
                    "control-label",
                ))
                for line in (pkg["updates"] + pkg["aur_updates"])[:14]:
                    pack(self.updates_box, wrap_label(f"• {line}", "hint"))
                if total > 14:
                    pack(self.updates_box, wrap_label(tr(f"… and {total - 14} more", f"… 还有 {total - 14} 项"), "hint"))
        elif pkg["orphans"]:
            pack(self.updates_box, wrap_label(
                tr("Orphans: ", "孤立包：") + ", ".join(pkg["orphans"][:8]), "hint",
            ))

        # Docker column
        if not dk["installed"]:
            pack(self.docker_box, wrap_label(tr("Docker is not installed on this machine.", "本机未安装 Docker。"), "hint"))
        elif not dk["running"]:
            pack(self.docker_box, wrap_label(
                tr("Docker daemon is stopped or requires docker group access.", "Docker 守护进程未运行或当前用户暂无权限。")
                + (f"\n{dk['error']}" if dk["error"] else ""),
                "hint",
            ))
            start_btn = style(Gtk.Button(label=tr("Start docker.service", "启动 Docker 服务")), "accent-button")
            start_btn.connect("clicked", lambda _: self._start_docker())
            pack(self.docker_box, start_btn)
        else:
            containers = dk["containers"]
            if not containers:
                pack(self.docker_box, wrap_label(tr("Docker is running; no containers found.", "Docker 服务运行中，当前没有容器。"), "hint"))
            for c in containers:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                col._row_expand = True
                pack(col, wrap_label(c["name"], "control-label"))
                sub = f"{c['image']} · {c['status']}"
                if c["ports"]:
                    sub += f"\n{c['ports']}"
                pack(col, wrap_label(sub, "hint"))
                running = c["state"] == "running"
                acts = Gtk.Box(spacing=4)
                pack(acts, status_badge(c["state"], "ok" if running else "warn"))
                tbtn = style(Gtk.Button(label=tr("Stop", "停止") if running else tr("Start", "启动")), "small-button")
                tbtn.connect("clicked", lambda _b, n=c["name"], a=("stop" if running else "start"): self._docker_op(n, a))
                rbtn = style(Gtk.Button(label=tr("Restart", "重启")), "small-button")
                rbtn.connect("clicked", lambda _b, n=c["name"]: self._docker_op(n, "restart"))
                pack(acts, tbtn)
                pack(acts, rbtn)
                pack(self.docker_box, data_row(col, acts))

        for container in (self.pkg_stats, self.updates_box, self.docker_box):
            container.show_all()

    def _ask_clean_cache(self):
        self._clear_confirm()
        bar, cancel = inline_confirm_bar(
            tr("Clean old Pacman package cache (keeps latest versions, requires Polkit)?",
               "确认清理旧版 Pacman 包缓存？（保留最新两版缓存，需要管理员授权）"),
            tr("Clean cache", "确认清理"),
            self._do_clean_cache,
            self._clear_confirm,
        )
        self.confirm_slot.add(bar)
        self.confirm_slot.set_no_show_all(False)
        self.confirm_slot.show_all()
        self.confirm_slot.set_no_show_all(True)
        cancel.grab_focus()

    def _do_clean_cache(self):
        self._clear_confirm()
        self._set_notice(tr("Cleaning pacman cache…", "正在清理 Pacman 缓存…"))
        self.panel.work(backend.clean_cache,
                        lambda _: (self.panel.feedback(tr("Package cache cleaned", "包缓存已清理")), self.refresh()),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _start_docker(self):
        self._set_notice(tr("Starting docker.service…", "正在启动 docker.service…"))
        self.panel.work(backend.start_docker_daemon, lambda _: self.refresh(),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _docker_op(self, name: str, action: str):
        self._set_notice(tr(f"Docker: {action} {name}…", f"正在对容器 {name} 执行 {action}…"))
        self.panel.work(lambda: backend.control_container(name, action),
                        lambda _: (self.panel.feedback(tr(f"Container {name}: {action}", f"容器 {name} 已完成 {action}")), self.refresh()),
                        lambda err: self._set_notice(str(err)), commit=True)
