"""Monitor & Processes page 2.0: live sparklines, interactive process killer & clean hardware summary."""
from __future__ import annotations

import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

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
from i18n import tr, tr_legacy
from page_host import PageEntry
from panel_support import box, button, label, scroller
import process_backend
from sparkline_widget import Sparkline


class SystemPage:
    def _build_system(self):
        from metrics import MetricsSampler
        self.metrics_sampler = MetricsSampler(detailed=True)
        self.process_sampler = process_backend.ProcessSampler()
        self.metrics_busy = False
        self.system_info_busy = False
        self._proc_sort = "cpu"
        self._proc_search_timer = None

        body = box(spacing=12)
        system_scroller = scroller(body)
        system_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)

        pack(body, nyx_guide_banner(
            "monitor",
            tr("Watch live CPU/RAM/GPU trend curves, search and safely terminate processes, and inspect full hardware specs.",
               "实时追踪处理器/内存/双显曲线、直接搜索并温和终止或强杀进程，无需再切去终端打开任务管理器。"),
            skin="engineer",
        ))

        header = pack(body, box(False, 6))
        pack(header, label(tr("LIVE TELEMETRY", "实时硬件遥测"), "section-title"), True)
        pack(header, label(tr("2 s interval", "每 2 秒刷新"), "hint"))

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        pack(body, grid)
        self.metric_values = {}
        self.metric_details = {}
        self.metric_bars = {}
        self.metric_sparks = {}
        spark_colors = {
            "cpu": (0.62, 0.66, 1.0),
            "memory": (1.0, 0.55, 0.78),
            "gpu": (0.49, 0.88, 0.75),
            "disk": (1.0, 0.85, 0.47),
        }
        for index, (key, title) in enumerate([
            ("cpu", tr("CPU", "处理器")), ("memory", tr("RAM", "内存")),
            ("gpu", tr("GPU", "显卡")), ("disk", tr("Storage (/)", "根目录存储")),
        ]):
            metric = box(spacing=5, css="metric-card")
            pack(metric, label(title, "hint"))
            self.metric_values[key] = pack(metric, label("—", "metric-value"))
            spark = Sparkline(spark_colors[key], max_points=45, height=28)
            self.metric_sparks[key] = pack(metric, spark)
            progress = Gtk.ProgressBar()
            progress.get_style_context().add_class("metric-progress")
            self.metric_bars[key] = pack(metric, progress)
            self.metric_details[key] = pack(metric, wrap_label(tr("Reading…", "读取中…"), "hint"))
            columns = 4 if self.panel_width >= 1220 else 2
            grid.attach(metric, index % columns, index // columns, 1, 1)

        # Interactive Process Manager Card
        proc_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        phdr = pack(proc_card, Gtk.Box(spacing=8))
        pack(phdr, label(tr("PROCESS MANAGER", "实时进程管理"), "section-title"), True)
        self.proc_search = Gtk.SearchEntry()
        self.proc_search.set_placeholder_text(tr("Search process or PID…", "搜索进程名或 PID…"))
        self.proc_search.connect("search-changed", self._on_proc_search)
        pack(phdr, self.proc_search)
        self.proc_sort_combo = Gtk.ComboBoxText()
        self.proc_sort_combo.append("cpu", tr("Sort: CPU", "按 CPU 排序"))
        self.proc_sort_combo.append("memory", tr("Sort: RAM", "按内存排序"))
        self.proc_sort_combo.append("name", tr("Sort: Name", "按名称排序"))
        self.proc_sort_combo.set_active_id("cpu")
        self.proc_sort_combo.connect("changed", self._on_proc_sort)
        pack(phdr, self.proc_sort_combo)

        self.proc_confirm_slot = pack(proc_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.proc_confirm_slot.set_no_show_all(True)
        self.proc_list = pack(proc_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5))
        pack(body, proc_card)

        # Two-column Network + Sensors & Hardware Summary
        wide = self.panel_width >= 1040
        lower = pack(body, card_grid(wide, 12))

        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        network = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(network, label(tr("NETWORK THROUGHPUT", "实时网络速率"), "section-title"))
        rates = pack(network, box(False, 10))
        for key, heading in [("download", tr("↓ Download", "↓ 下载")), ("upload", tr("↑ Upload", "↑ 上传"))]:
            side = pack(rates, box(spacing=4), True)
            pack(side, label(heading, "hint"))
            self.metric_values[key] = pack(side, label("—", "network-rate"))
        self.network_detail = pack(network, wrap_label("", "hint"))
        pack(left_col, network)

        sensors_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(sensors_card, label(tr("THERMALS & UPTIME", "温度传感器与运行时间"), "section-title"))
        self.sensor_detail = pack(sensors_card, wrap_label("", "hint"))
        sensors_exp = Gtk.Expander(label=tr("All temperature sensors", "展开全部温度传感器"))
        self.sensor_readings = wrap_label("", "spec-value")
        sensors_exp.add(self.sensor_readings)
        pack(sensors_card, sensors_exp)
        pack(left_col, sensors_card)
        grid_add(lower, left_col)

        # Right column: Structured System Specs (single non-duplicated truth)
        system = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        shdr = pack(system, Gtk.Box(spacing=8))
        pack(shdr, label(tr("ABOUT THIS SYSTEM", "系统与硬件规格"), "section-title"), True)
        self.system_copy = pack(shdr, button(tr("Copy", "复制"), self.copy_system_info, "small-button"))
        self.system_refresh_button = pack(shdr, button(tr("Refresh", "刷新"), self.refresh_system_info, "small-button"))
        self.system_specs = Gtk.Grid(column_spacing=14, row_spacing=6)
        pack(system, self.system_specs)
        self.system_specs_placeholder = label(tr("Reading system…", "正在读取硬件规格…"), "hint")
        self.system_specs.attach(self.system_specs_placeholder, 0, 0, 2, 1)
        self.system_detail = label("", "system-summary", localize=False)
        self.system_detail.set_no_show_all(True)
        self.system_detail.set_visible(False)
        self.display_detail = wrap_label("", "hint")
        self.display_detail.set_no_show_all(True)
        self.inventory_labels = []
        grid_add(lower, system)

        return PageEntry(body, system_scroller)

    def _on_proc_search(self, *_):
        if self._proc_search_timer is not None:
            GLib.source_remove(self._proc_search_timer)
        self._proc_search_timer = GLib.timeout_add(160, self._debounced_proc)

    def _debounced_proc(self):
        self._proc_search_timer = None
        self.refresh_metrics()
        return GLib.SOURCE_REMOVE

    def _on_proc_sort(self, combo):
        self._proc_sort = combo.get_active_id() or "cpu"
        self.refresh_metrics()

    def _clear_proc_confirm(self):
        for child in self.proc_confirm_slot.get_children():
            child.destroy()
        self.proc_confirm_slot.hide()

    def _terminate_proc(self, proc: dict, *, force: bool = False):
        if force:
            self._clear_proc_confirm()
            bar, cancel = inline_confirm_bar(
                tr(f"Force kill (SIGKILL) {proc['name']} (PID {proc['pid']})? Unsaved data may be lost.",
                   f"确认强制结束进程 {proc['name']}（PID {proc['pid']}）？未保存数据可能丢失。"),
                tr("Force kill", "确认强杀"),
                lambda: self._do_signal(proc["pid"], True),
                self._clear_proc_confirm,
            )
            self.proc_confirm_slot.add(bar)
            self.proc_confirm_slot.set_no_show_all(False)
            self.proc_confirm_slot.show_all()
            self.proc_confirm_slot.set_no_show_all(True)
            cancel.grab_focus()
        else:
            self._do_signal(proc["pid"], False)

    def _do_signal(self, pid: int, force: bool):
        self._clear_proc_confirm()
        self.work(
            lambda: process_backend.signal_process(pid, force=force),
            lambda _: (self.feedback(tr(f"Sent signal to PID {pid}", f"已向进程 {pid} 发送终止信号")), self.refresh_metrics()),
            lambda err: self.feedback(str(err), True),
            commit=True,
        )

    def start_metrics_tick(self):
        if self.metrics_tick_source is None and self.alive:
            self.metrics_tick_source = GLib.timeout_add_seconds(2, self.refresh_metrics)
            self.pending.add(self.metrics_tick_source)

    def stop_metrics_tick(self):
        source = self.metrics_tick_source
        self.metrics_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def refresh_metrics(self, *, prime=False):
        if not self.alive or getattr(self, "metrics_sampler", None) is None:
            return GLib.SOURCE_REMOVE
        visible_monitor = lambda: self.page_visible("monitor") or self.page_visible("system")
        if not visible_monitor():
            return GLib.SOURCE_CONTINUE
        if not self.metrics_busy:
            self.metrics_busy = True
            generation = getattr(self, "metrics_generation", 0)
            valid = lambda: self.alive and generation == getattr(self, "metrics_generation", 0)
            proc_sampler = getattr(self, "process_sampler", None)
            query = self.proc_search.get_text().strip() if getattr(self, "proc_search", None) else ""
            sort_by = getattr(self, "_proc_sort", "cpu")

            def task():
                if not valid():
                    return None
                if prime:
                    self.metrics_sampler.prime()
                    if proc_sampler is not None:
                        proc_sampler.sample(limit=5)
                        time.sleep(0.05)
                if not valid():
                    return None
                self.metrics_sampler.gpu_read_allowed = valid
                vals = self.metrics_sampler.sample()
                procs = proc_sampler.sample(query=query, sort_by=sort_by, limit=18) if proc_sampler is not None else None
                return vals, procs

            def complete(payload=None, error=None):
                self.metrics_busy = False
                if not valid() or (payload is None and error is None):
                    if visible_monitor():
                        self.refresh_metrics(prime=True)
                    return
                if error is not None:
                    self.metrics_error(error)
                else:
                    vals, procs = payload
                    self.apply_metrics(vals)
                    if procs is not None:
                        self._render_processes(procs)
            self.work(task, complete, lambda error: complete(error=error))
        return GLib.SOURCE_CONTINUE

    def _render_processes(self, procs: list[dict]):
        from metrics import format_bytes
        if not getattr(self, "proc_list", None):
            return
        for child in self.proc_list.get_children():
            child.destroy()
        if not procs:
            pack(self.proc_list, wrap_label(tr("No matching processes.", "没有匹配的进程。"), "hint"))
        for p in procs:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col._row_expand = True
            pack(col, wrap_label(f"{p['name']}  (PID {p['pid']})", "control-label"))
            pack(col, wrap_label(f"{p['user']} · {p['cmdline'][:80]}", "hint"))
            cpu_b = status_badge(f"CPU {p['cpu']:.1f}%", "warn" if p["cpu"] >= 40 else "info")
            ram_b = status_badge(format_bytes(p["rss"]), "info")
            acts = Gtk.Box(spacing=4)
            pack(acts, cpu_b)
            pack(acts, ram_b)
            if not p["protected"]:
                term = style(Gtk.Button(label=tr("End", "结束")), "small-button")
                term.set_tooltip_text(tr("Send SIGTERM (graceful)", "温和终止进程（SIGTERM）"))
                term.connect("clicked", lambda _b, item=p: self._terminate_proc(item, force=False))
                kill = style(Gtk.Button(label="×"), "flat")
                kill.set_tooltip_text(tr("Force kill (SIGKILL)", "强制杀死进程（SIGKILL）"))
                kill.connect("clicked", lambda _b, item=p: self._terminate_proc(item, force=True))
                pack(acts, term)
                pack(acts, kill)
            pack(self.proc_list, data_row(col, acts))
        self.proc_list.show_all()

    def metrics_error(self, error):
        self.metrics_busy = False
        self.sensor_detail.set_text(tr("Monitoring unavailable", "监控不可用") + f"\n{error}")

    def apply_metrics(self, values):
        from metrics import format_bytes, format_percent, format_rate, format_uptime, gpu_activity_text
        self.metrics_busy = False
        unavailable = tr("Unavailable", "不可用")

        def metric(key, percent, detail):
            self.metric_values[key].set_text(format_percent(percent))
            self.metric_bars[key].set_fraction(max(0, min(1, percent / 100)) if percent is not None else 0)
            self.metric_bars[key].set_sensitive(percent is not None)
            self.metric_details[key].set_text(detail)
            spark = self.metric_sparks.get(key)
            if spark is not None:
                spark.push(percent)

        load = values.get("load_average")
        metric("cpu", values.get("cpu_percent"),
               tr("Load ", "负载 ") + " / ".join(f"{value:.2f}" for value in load) if load else unavailable)
        memory = values.get("memory") or {}
        metric("memory", memory.get("percent"),
               f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])}" if memory else unavailable)
        disk = values.get("disk") or {}
        metric("disk", disk.get("percent"),
               tr(f"{format_bytes(disk['free'])} free", f"可用 {format_bytes(disk['free'])}") if disk else unavailable)
        gpus = values.get("gpus") or []
        measured = [item for item in gpus if item.get("percent") is not None]
        gpu = max(measured, key=lambda item: item["percent"]) if measured else (gpus[0] if gpus else {})
        gpu_lines = []
        for item in gpus:
            parts = [item.get("name") or "GPU", gpu_activity_text(item)]
            if item.get("temperature") is not None:
                parts.append(f"{item['temperature']:.0f}°C")
            if item.get("memory_used") is not None and item.get("memory_total") is not None:
                parts.append(f"VRAM {format_bytes(item['memory_used'])} / {format_bytes(item['memory_total'])}")
            gpu_lines.append(" · ".join(parts))
        metric("gpu", gpu.get("percent"), "\n".join(gpu_lines) or unavailable)

        network = values.get("network") or {}
        self.metric_values["download"].set_text(format_rate(network.get("down_bps")))
        self.metric_values["upload"].set_text(format_rate(network.get("up_bps")))
        self.network_detail.set_text(network.get("interface") or tr("No active interface", "无活动网络接口"))

        sensors = [tr("Uptime ", "已运行 ") + format_uptime(values.get("uptime_seconds"))]
        swap = values.get("swap")
        if swap:
            sensors.append(tr("Swap ", "交换分区 ") + f"{format_bytes(swap['used'])} / {format_bytes(swap['total'])}")
        temperatures = values.get("temperatures") or []
        if temperatures:
            measured_t = [item["celsius"] for item in temperatures if item.get("celsius") is not None]
            if measured_t:
                sensors.append(tr(f"Peak {max(measured_t):.0f}°C · {len(temperatures)} sensors",
                                  f"最高温度 {max(measured_t):.0f}°C · {len(temperatures)} 个传感器"))
            self.sensor_readings.set_text("\n".join(
                item["name"] + " · " + (f"{item['celsius']:.0f}°C" if item.get("celsius") is not None else unavailable)
                for item in temperatures
            ))
        else:
            self.sensor_readings.set_text(tr("No temperature sensors", "无温度传感器"))
        self.sensor_detail.set_text(" · ".join(sensors))

    def refresh_system_info(self):
        if not self.alive or getattr(self, "system_info_busy", None) is None:
            return
        if self.system_info_busy or not self.page_visible("monitor"):
            return
        self.system_info_busy = True
        refresh_button = getattr(self, "system_refresh_button", None)
        if refresh_button is not None:
            refresh_button.set_sensitive(False)

        def read():
            from system_info import collect, plain_text
            rows, outputs = collect()
            return rows, plain_text(rows), self.describe_outputs(outputs)

        def done(result):
            rows, text_val, display = result
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(text_val)
            self.populate_system_specs(rows)
            self.display_detail.set_text(display)

        def failed(error):
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(tr("Unavailable", "不可用") + f"\n{error}")

        self.work(read, done, failed)

    def populate_system_specs(self, rows):
        for child in self.system_specs.get_children():
            self.system_specs.remove(child)
            child.destroy()
        for index, (key, value) in enumerate(rows):
            key_label = label(key, "spec-key", localize=False)
            key_label.set_size_request(130 if self.panel_width >= 1200 else 104, -1)
            value_label = label(value, "spec-value", wrap=True, localize=False)
            value_label.set_hexpand(True)
            value_label.set_max_width_chars(56 if self.panel_width >= 1200 else 36)
            value_label.set_selectable(True)
            self.system_specs.attach(key_label, 0, index, 1, 1)
            self.system_specs.attach(value_label, 1, index, 1, 1)
        self.system_specs.show_all()

    def copy_system_info(self):
        content = self.system_detail.get_text()
        self.work(lambda: subprocess.run(["wl-copy"], input=content, capture_output=True,
                                         text=True, check=True, timeout=5),
                  lambda _: self.feedback(tr("System information copied", "系统信息已复制")), commit=True)

    @staticmethod
    def describe_outputs(outputs):
        if not isinstance(outputs, dict) or not outputs:
            return tr("Display information unavailable", "无法读取屏幕信息")
        descriptions = []
        for name, output in outputs.items():
            if not isinstance(output, dict):
                continue
            modes = output.get("modes") or []
            current = output.get("current_mode")
            detail = tr("Off", "已关闭")
            if isinstance(current, int) and 0 <= current < len(modes):
                mode = modes[current]
                detail = f"{mode.get('width', '?')} × {mode.get('height', '?')}"
                refresh = mode.get("refresh_rate")
                if isinstance(refresh, (int, float)):
                    detail += f" · {refresh / 1000:g} Hz"
            logical = output.get("logical") or {}
            if logical.get("scale") is not None:
                detail += f" · {logical['scale']:g}×"
            descriptions.append(f"{name} · {output.get('model') or output.get('make') or 'Display'}\n{detail}")
        return "\n\n".join(descriptions) or tr("No displays", "未检测到屏幕")
