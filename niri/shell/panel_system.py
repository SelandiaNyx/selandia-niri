"""System page: metrics, power actions and the hardware summary.

Mixed into ``panel.Panel``; methods rely on the panel's shared state
(``self.work``, ``self.feedback`` and the widgets built in ``__init__``).
"""
from __future__ import annotations

import subprocess
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Pango

from i18n import tr, tr_legacy
from page_host import PageEntry
from panel_support import box, button, label, pack, scroller


class SystemPage:
    def _build_system(self):
        from metrics import MetricsSampler
        self.metrics_sampler = MetricsSampler(detailed=True)
        self.metrics_busy = False
        self.system_info_busy = False
        body = box(spacing=12)
        system_scroller = scroller(body)
        # The live readings make this page taller than the window. Reserve the
        # gutter from the first frame so the first sample cannot shift cards
        # sideways when the scrollbar appears.
        system_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        header = pack(body, box(False, 6))
        pack(header, label(tr_legacy("LIVE  /  实时监控"), "section-title"), True)
        pack(header, label(tr("Live rates · 2 s", "实时速率 · 每两秒"), "hint"))
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        pack(body, grid)
        self.metric_values = {}
        self.metric_details = {}
        self.metric_bars = {}
        for index, (key, title) in enumerate([
            ("cpu", tr_legacy("CPU · 处理器")), ("memory", tr_legacy("RAM · 内存")),
            ("gpu", tr_legacy("GPU · 显卡")), ("disk", tr_legacy("Storage · 根目录")),
        ]):
            metric = box(spacing=6, css="metric-card")
            pack(metric, label(title, "hint"))
            self.metric_values[key] = pack(metric, label("—", "metric-value"))
            progress = Gtk.ProgressBar()
            progress.get_style_context().add_class("metric-progress")
            self.metric_bars[key] = pack(metric, progress)
            self.metric_details[key] = pack(metric, self.compact_label(tr_legacy("Reading… · 读取中…")))
            columns = 4 if self.panel_width >= 1300 else 2
            grid.attach(metric, index % columns, index // columns, 1, 1)
        system = self.card(body, tr_legacy("ABOUT THIS SYSTEM  /  系统信息"))
        tools = pack(system, box(False, 8))
        self.system_copy = pack(tools, button(tr("Copy system information", "复制系统信息"), self.copy_system_info, "small-button"))
        self.system_refresh_button = pack(tools, button(tr_legacy("Refresh displays & system · 刷新屏幕与系统"), self.refresh_system_info, "small-button"))
        self.system_specs = Gtk.Grid(column_spacing=18, row_spacing=9)
        pack(system, self.system_specs)
        self.system_specs_placeholder = label(tr_legacy("Reading system… · 读取系统…"), "hint")
        self.system_specs.attach(self.system_specs_placeholder, 0, 0, 2, 1)
        # Kept selectable but hidden: copy/export still has the complete text,
        # while the visible card is a structured key/value table instead of a
        # terminal dump.
        self.system_detail = label("", "system-summary", localize=False)
        self.system_detail.set_no_show_all(True)
        self.system_detail.set_visible(False)
        self.system_detail.set_selectable(True)
        network = self.card(body, tr_legacy("NETWORK  /  网络速率"))
        rates = pack(network, box(False, 10))
        for key, heading in [("download", tr_legacy("↓ Download · 下载")), ("upload", tr_legacy("↑ Upload · 上传"))]:
            side = pack(rates, box(spacing=4), True)
            pack(side, label(heading, "hint"))
            self.metric_values[key] = pack(side, label("—", "network-rate"))
        self.network_detail = pack(network, self.compact_label())
        self.sensor_detail = pack(body, self.compact_label())
        sensors = Gtk.Expander(label=tr_legacy("All temperature sensors · 全部温度传感器"))
        self.sensor_readings = self.compact_label()
        sensor_scroll = scroller(self.sensor_readings)
        sensor_scroll.set_min_content_height(140)
        sensor_scroll.set_max_content_height(180)
        sensor_scroll.set_propagate_natural_height(True)
        sensors.add(sensor_scroll)
        pack(body, sensors)
        pack(body, button(tr_legacy("Open process monitor · 查看进程"), lambda: self.desktop("system-monitor")))
        self.inventory = pack(body, Gtk.FlowBox())
        self.inventory.set_selection_mode(Gtk.SelectionMode.NONE)
        self.inventory.set_min_children_per_line(1)
        self.inventory.set_max_children_per_line(2 if self.panel_width >= 1200 else 1)
        self.inventory.set_column_spacing(12)
        self.inventory.set_row_spacing(12)
        self.inventory_labels = []
        from metrics import detailed_sections
        for heading, content in detailed_sections({}):
            card = box(spacing=8, css="card")
            pack(card, label(heading, "section-title", wrap=True))
            value = pack(card, label(content, "system-inventory", wrap=True, localize=False))
            value.set_selectable(True)
            value.set_max_width_chars(44)
            self.inventory_labels.append(value)
            self.inventory.add(card)
        display = self.card(body, tr_legacy("DISPLAYS  /  屏幕设置"))
        self.display_detail = pack(display, self.compact_label(tr_legacy("Reading displays… · 读取显示器…")))
        self.display_detail.set_selectable(True)
        pack(display, button(tr_legacy("Resolution, scale & layout · 分辨率、缩放与排列"),
                             lambda: self.select_control_tab("displays"), "tool-button"))
        pack(display, self.compact_label(tr_legacy("Set resolution, refresh, scale and bit-depth limit in Screen.\n在屏幕页直接设置分辨率、刷新率、缩放和位深上限。")))
        maintenance = self.card(body, tr_legacy("MAINTENANCE  /  系统维护"))
        self.action_grid(maintenance, [
            (tr_legacy("↻  Update · 系统更新"), lambda: self.desktop("updates")),
            (tr_legacy("⚒  Repair · 修复桌面"), lambda: self.desktop("repair")),
            (tr_legacy("✓  Status · 安装状态"), lambda: self.desktop("status")),
            (tr_legacy("⌕  Diagnose · 完整自检"), lambda: self.desktop("check")),
        ])
        pack(maintenance, self.compact_label(tr_legacy("Update opens a terminal for a full Arch upgrade. Review packages before confirming.\n更新将打开终端执行完整 Arch 升级，请检查软件包后确认。")))
        utilities = self.card(body, tr_legacy("UTILITIES  /  实用工具"))
        self.action_grid(utilities, [
            (tr_legacy("▤  Files · 文件"), lambda: self.desktop("launch", "files")),
            (tr_legacy("⌘  Terminal · 终端"), lambda: self.desktop("launch", "terminal")),
            (tr_legacy("▧  Wallpaper · 壁纸"), lambda: self.desktop("wallpaper")),
            (tr_legacy("⌖  Screenshot · 截图"), lambda: self.launch(["niri", "msg", "action", "screenshot"])),
        ])
        return PageEntry(body, system_scroller)

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

    def action_grid(self, parent, actions):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        pack(parent, grid)
        for index, (title, callback) in enumerate(actions):
            grid.attach(button(title, callback, "tool-button"), index % 2, index // 2, 1, 1)

    def refresh_metrics(self, *, prime=False):
        if not self.alive or getattr(self, "metrics_sampler", None) is None:
            return GLib.SOURCE_REMOVE
        if not self.page_visible('system'):
            return GLib.SOURCE_CONTINUE
        if not self.metrics_busy:
            self.metrics_busy = True
            generation = getattr(self, 'metrics_generation', 0)
            valid = lambda: self.alive and generation == getattr(self, 'metrics_generation', 0)

            def task():
                if not valid():
                    return None
                if prime:
                    self.metrics_sampler.prime()
                    time.sleep(0.05)
                if not valid():
                    return None
                self.metrics_sampler.gpu_read_allowed = valid
                return self.metrics_sampler.sample()

            def complete(value=None, error=None):
                self.metrics_busy = False
                if not valid() or value is None and error is None:
                    if self.page_visible('system'):
                        self.refresh_metrics(prime=True)
                    return
                if error is not None:
                    self.metrics_error(error)
                else:
                    self.apply_metrics(value)
            self.work(task, complete, lambda error: complete(error=error))
        return GLib.SOURCE_CONTINUE

    def metrics_error(self, error):
        self.metrics_busy = False
        self.sensor_detail.set_text(tr("Monitoring unavailable", "监控不可用") + f"\n{error}")

    def apply_metrics(self, values):
        from metrics import detailed_sections
        for widget, (_heading, content) in zip(self.inventory_labels, detailed_sections(values)):
            widget.set_text(content)
        from metrics import format_bytes, format_rate, format_percent, format_uptime, gpu_activity_text
        self.metrics_busy = False
        unavailable = tr_legacy("Unavailable · 不可用")

        def metric(key, percent, detail):
            self.metric_values[key].set_text(format_percent(percent))
            self.metric_bars[key].set_fraction(max(0, min(1, percent / 100)) if percent is not None else 0)
            self.metric_bars[key].set_sensitive(percent is not None)
            self.metric_details[key].set_text(detail)

        load = values.get("load_average")
        metric("cpu", values.get("cpu_percent"),
               tr("Load ", "负载 ") + " / ".join(f"{value:.2f}" for value in load) if load else unavailable)
        memory = values.get("memory") or {}
        metric("memory", memory.get("percent"),
               f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])}" if memory else unavailable)
        disk = values.get("disk") or {}
        metric("disk", disk.get("percent"), tr(f"{format_bytes(disk['free'])} free", f"可用 {format_bytes(disk['free'])}") if disk else unavailable)
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
        self.network_detail.set_text(network.get("interface") or tr_legacy("No active interface · 无活动网络接口"))
        sensors = [tr("Uptime ", "已运行 ") + format_uptime(values.get('uptime_seconds'))]
        swap = values.get("swap")
        if swap:
            sensors.append(tr("Swap ", "交换分区 ") + f"{format_bytes(swap['used'])} / {format_bytes(swap['total'])}")
        temperatures = values.get("temperatures") or []
        if temperatures:
            measured_temperatures = [item['celsius'] for item in temperatures if item.get('celsius') is not None]
            if measured_temperatures:
                sensors.append(tr(f"Peak {max(measured_temperatures):.0f}°C · {len(temperatures)} sensors",
                                  f"最高温度 {max(measured_temperatures):.0f}°C · {len(temperatures)} 个传感器"))
            else:
                sensors.append(tr_legacy("Temperature unavailable · 温度不可用"))
            self.sensor_readings.set_text("\n".join(item['name'] + " · " +
                (f"{item['celsius']:.0f}°C" if item.get('celsius') is not None else unavailable) for item in temperatures))
        else:
            sensors.append(tr_legacy("Temperature unavailable · 温度不可用"))
            self.sensor_readings.set_text(tr_legacy("No temperature sensors · 无温度传感器"))
        self.sensor_detail.set_text("\n".join(sensors))

    def refresh_system_info(self):
        if not self.alive or getattr(self, "system_info_busy", None) is None:
            return
        if self.system_info_busy:
            return
        # A display transaction can finish after the user left this page. The
        # page is refreshed on re-entry, so hidden work must not scan the host.
        if not self.page_visible('system'):
            return
        self.system_info_busy = True
        refresh_button = getattr(self, 'system_refresh_button', None)
        if refresh_button is not None:
            refresh_button.set_sensitive(False)

        def read():
            from system_info import collect, plain_text
            rows, outputs = collect()
            return rows, plain_text(rows), self.describe_outputs(outputs)

        def done(result):
            rows, text, display = result
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(text)
            self.populate_system_specs(rows)
            self.display_detail.set_text(display)

        def failed(error):
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(tr("Unavailable", "不可用") + f"\n{error}")
            for child in self.system_specs.get_children():
                self.system_specs.remove(child)
                child.destroy()
            self.system_specs.attach(label(tr("Unavailable", "不可用") + f"\n{error}", "hint"), 0, 0, 2, 1)
            self.system_specs.show_all()
        self.work(read, done, failed)

    def populate_system_specs(self, rows):
        for child in self.system_specs.get_children():
            self.system_specs.remove(child)
            child.destroy()
        for index, (key, value) in enumerate(rows):
            key_label = label(key, "spec-key", localize=False)
            key_label.set_size_request(150 if self.panel_width >= 1200 else 112, -1)
            value_label = label(value, "spec-value", wrap=True, localize=False)
            value_label.set_hexpand(True)
            value_label.set_max_width_chars(72 if self.panel_width >= 1200 else 38)
            value_label.set_selectable(True)
            self.system_specs.attach(key_label, 0, index, 1, 1)
            self.system_specs.attach(value_label, 1, index, 1, 1)
        self.system_specs.show_all()

    def align_system_info(self):
        keys = [line.split("\t", 1)[0] for line in self.system_detail.get_text().splitlines() if "\t" in line]
        if keys:
            stop = max(self.system_detail.create_pango_layout(key).get_pixel_size()[0] for key in keys) + 12
            tabs = Pango.TabArray.new(1, True)
            tabs.set_tab(0, Pango.TabAlign.LEFT, stop)
            self.system_detail.get_layout().set_tabs(tabs)

    def copy_system_info(self):
        # Capture the visible text now, not a new sample or hidden inventory.
        content = self.system_detail.get_text()
        self.work(lambda: subprocess.run(["wl-copy"], input=content, capture_output=True,
                                         text=True, check=True, timeout=5),
                  lambda _: self.feedback(tr("System information copied", "系统信息已复制")), commit=True)

    @staticmethod
    def describe_outputs(outputs):
        if not isinstance(outputs, dict) or not outputs:
            return tr_legacy("Display information unavailable · 无法读取屏幕信息")
        descriptions = []
        for name, output in outputs.items():
            if not isinstance(output, dict):
                continue
            modes = output.get("modes") or []
            current = output.get("current_mode")
            detail = tr_legacy("Off · 已关闭")
            if isinstance(current, int) and 0 <= current < len(modes):
                mode = modes[current]
                detail = f"{mode.get('width', '?')} × {mode.get('height', '?')}"
                refresh = mode.get("refresh_rate")
                if isinstance(refresh, (int, float)):
                    detail += f" · {refresh / 1000:g} Hz"
            logical = output.get("logical") or {}
            if logical.get("scale") is not None:
                detail += f" · {logical['scale']:g}×"
            if logical.get("x") is not None and logical.get("y") is not None:
                detail += tr("\nPosition ", "\n位置 ") + f"{logical['x']}, {logical['y']}"
            descriptions.append(f"{name} · {output.get('model') or output.get('make') or 'Display'}\n{detail}")
        return "\n\n".join(descriptions) or tr_legacy("No displays · 未检测到屏幕")
