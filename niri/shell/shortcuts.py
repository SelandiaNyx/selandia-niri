"""Build the searchable guide from the actual bindings, including hidden aliases.

Every built-in description is stored as an explicit ``(english, chinese)`` pair
and rendered with one ``tr()`` template, so no language ever shows a mixed or
truncated sentence. User data - commands, custom overlay titles, device and file
names - is preserved verbatim in both languages. ``search`` additionally indexes
both languages so one query finds the same binding either way.
"""
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
NODE = re.compile(r'^\s*([\w+]+)\s+([^{}\n]*?)\{((?:"(?:\\.|[^"\\])*"|[^{}"])*?)\}', re.M)
# Tokenize comments before searching nodes, so command strings containing // stay intact.
TOKENS = re.compile(r'r(#+)?".*?"\1|"(?:\\.|[^"\\])*"|//[^\n]*|/\*|\*/|[{}]', re.S)


def binding_sections(source):
    masked = list(source)
    depth = 0
    start = 0
    for token in TOKENS.finditer(source):
        value = token[0]
        if value == "/*":
            if not depth:
                start = token.start()
            depth += 1
        elif value == "*/" and depth:
            depth -= 1
            if not depth:
                masked[start:token.end()] = ["\n" if char == "\n" else " " for char in source[start:token.end()]]
        elif value.startswith("//") and not depth:
            masked[token.start():token.end()] = " " * len(value)
    if depth:
        masked[start:] = " " * (len(source) - start)
    text = "".join(masked)
    for match in re.finditer(r"(?m)^\s*binds\s*\{", text):
        depth = 1
        for token in TOKENS.finditer(text, match.end()):
            if token[0] == "{":
                depth += 1
            elif token[0] == "}":
                depth -= 1
                if not depth:
                    yield text[match.end():token.start()]
                    break
ACTION = {
    "show-hotkey-overlay": ("Native shortcut overlay", "原生快捷键提示"),
    "toggle-overview": ("Workspace overview", "工作区总览"),
    "close-window": ("Close window", "关闭窗口"),
    "fullscreen-window": ("Fullscreen", "全屏"),
    "maximize-column": ("Maximize column", "最大化列"),
    "toggle-window-floating": ("Toggle floating", "切换浮动"),
    "switch-focus-between-floating-and-tiling": ("Focus floating or tiled window", "切换浮动与平铺焦点"),
    "switch-preset-column-width": ("Next column width", "下一档列宽"),
    "switch-preset-column-width-back": ("Previous column width", "上一档列宽"),
    "switch-preset-window-height": ("Next window height", "下一档高度"),
    "set-column-width": ("Adjust column width", "调整列宽"),
    "set-window-height": ("Adjust window height", "调整高度"),
    "center-column": ("Center column", "居中当前列"),
    "consume-or-expel-window-left": ("Merge or detach to the left", "向左合并或拆出"),
    "consume-or-expel-window-right": ("Merge or detach to the right", "向右合并或拆出"),
    "toggle-column-tabbed-display": ("Toggle column tabs", "切换标签页列"),
    "focus-window-previous": ("Previous window", "上一个窗口"),
    "toggle-keyboard-shortcuts-inhibit": ("Toggle shortcut inhibition", "切换快捷键接管"),
    "quit": ("Quit Niri with confirmation", "确认退出 Niri"),
    "screenshot": ("Interactive screenshot", "交互截图"),
    "screenshot-screen": ("Screenshot screen", "屏幕截图"),
    "screenshot-window": ("Screenshot window", "窗口截图"),
}
DESKTOP = {
    "launch terminal": ("Terminal", "终端"),
    "launch files": ("File manager", "文件管理器"),
    "launch browser": ("Browser", "浏览器"),
    "launch editor": ("Code editor", "代码编辑器"),
    "launcher": ("App launcher", "应用启动器"),
    "clipboard": ("Clipboard history", "剪贴板历史"),
    "clipboard-clear": ("Clear clipboard with confirmation", "确认清空剪贴板"),
    "lock": ("Lock screen", "锁屏"),
    "sleep": ("Suspend", "睡眠"),
    "power": ("Power menu", "电源菜单"),
    "wallpaper": ("Choose wallpaper", "更换壁纸"),
    "reload": ("Validate and reload desktop", "校验并重载桌面"),
    "bar-toggle": ("Show or hide status bar", "显示或隐藏状态栏"),
    "idle-toggle": ("Keep awake", "保持唤醒"),
    "shortcuts": ("Search every shortcut", "搜索全部快捷键"),
    "control": ("Control Center", "控制中心"),
    "ai": ("AI sidebar", "AI 侧栏"),
    "codex": ("Codex terminal sidebar", "Codex 终端侧栏"),
    "volume up": ("Volume up", "提高音量"),
    "volume down": ("Volume down", "降低音量"),
    "volume mute": ("Mute speakers", "扬声器静音"),
    "volume mic": ("Mute microphone", "麦克风静音"),
    "brightness up": ("Brightness up", "提高亮度"),
    "brightness down": ("Brightness down", "降低亮度"),
}
MEDIA = {"next": ("Next track", "下一曲"), "previous": ("Previous track", "上一曲"),
         "play-pause": ("Play or pause", "播放或暂停"), "play": ("Play", "播放"),
         "pause": ("Pause", "暂停"), "stop": ("Stop playback", "停止播放")}
DIRECTIONS = {"left": ("Left", "左"), "right": ("Right", "右"), "up": ("Up", "上"), "down": ("Down", "下")}
CAPTURE = {"clipboard": ("clipboard only", "仅剪贴板"), "save": ("save and clipboard", "保存及剪贴板")}
OTHER = ("Custom", "自定义")


def entry(keys, english, chinese, category):
    keys = keys.replace("Mod", "Super").replace("Page_", "Page")
    return {"keys": keys, "description": (english, chinese), "category": category,
            "search": " ".join((keys, english, chinese, *category)).casefold()}


def describe(body, attributes):
    """Return (english, chinese, category_english, category_chinese)."""
    action = body.strip().split()[0].rstrip(";")
    if re.search(r'"niri"\s+"msg"\s+"action"\s+"power-on-monitors"', body):
        return "Wake display output", "恢复显示输出", "Displays", "显示器"
    if "scripts/desktop" in body:
        command = body.split("scripts/desktop", 1)[1].replace('\\"', '').strip().rstrip(';').strip().strip('"').strip()
        english, chinese = DESKTOP.get(command, (command, command))
        return english, chinese, "Desktop", "桌面"
    if '"swaync-client"' in body:
        return "Notifications", "通知中心", "Desktop", "桌面"
    if '"playerctl"' in body:
        for name, (english, chinese) in MEDIA.items():
            if f'"{name}"' in body:
                return english, chinese, "Media", "媒体"
    if action in ACTION:
        english, chinese = ACTION[action]
        if action in ("set-column-width", "set-window-height"):
            arguments = " ".join(re.findall(r'"([^"\\]*)"', body))
            english, chinese = f"{english} {arguments}".strip(), f"{chinese} {arguments}".strip()
        if action == "screenshot-screen":
            # The save mode is part of the meaning and must survive translation.
            mode = "clipboard" if "write-to-disk=false" in body else "save"
            english += " (" + CAPTURE[mode][0] + ")"
            chinese += "（" + CAPTURE[mode][1] + "）"
        category = ("Capture", "截图") if action.startswith("screenshot") else ("Windows", "窗口")
        return english, chinese, *category
    if "workspace" in action:
        target = re.findall(r'"([^"\\]*)"', body)
        if action.endswith("-up"):
            destination = ("previous workspace", "上一个工作区")
        elif action.endswith("-down"):
            destination = ("next workspace", "下一个工作区")
        else:
            destination = (f"workspace {target[0]}", f"工作区 {target[0]}") if target else ("workspace", "工作区")
        if action.startswith("focus-"):
            return f"Go to {destination[0]}", f"切换到{destination[1]}", "Workspaces", "工作区"
        follow = ("focus stays", "焦点留在原处") if "focus=false" in body else ("window follows", "窗口跟随")
        return (f"Move to {destination[0]} ({follow[0]})", f"移至{destination[1]}（{follow[1]}）",
                "Workspaces", "工作区")
    parts = action.split("-")
    if parts[-1] in DIRECTIONS and parts[0] in ("focus", "move"):
        verb = ("Focus", "聚焦") if parts[0] == "focus" else ("Move", "移动")
        subject = ("Monitor", "显示器") if "monitor" in parts else ("Column", "列") if "column" in parts else ("Window", "窗口")
        direction = DIRECTIONS[parts[-1]]
        category = ("Displays", "显示器") if "monitor" in parts else ("Windows", "窗口")
        return (f"{verb[0]} · {subject[0]} · {direction[0]}", f"{verb[1]} · {subject[1]} · {direction[1]}", *category)
    title = re.search(r'hotkey-overlay-title="([^"\n]+)"', attributes)
    # User data is never translated: the same text is shown in either language.
    custom = title[1] if title else body.strip().rstrip(";").strip()
    return custom, custom, *OTHER


def load_shortcuts():
    bindings = {}
    for file in (BASE / "conf/binds.kdl", BASE / "conf/local.kdl"):
        if not file.exists():
            continue
        for section in binding_sections(file.read_text()):
            for match in NODE.finditer(section):
                keys, attributes, body = match.groups()
                if not body.strip():
                    continue
                english, chinese, category_english, category_chinese = describe(body, attributes)
                bindings[keys] = entry(keys, english, chinese, (category_english, category_chinese))
    bindings["mouse-move"] = entry("Mod + Left drag", "Move window", "拖动窗口", ("Mouse", "鼠标"))
    bindings["mouse-resize"] = entry("Mod + Right drag", "Resize window", "调整窗口大小", ("Mouse", "鼠标"))
    return list(bindings.values())
