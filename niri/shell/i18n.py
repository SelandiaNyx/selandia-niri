"""Small, explicit translations for this desktop's own interface text.

Device names, file paths, media metadata and chat messages are never translated.
The legacy helper is only for existing, UI-owned bilingual labels.
"""
from __future__ import annotations

import os
import re
import sys

_language_override = None
_CJK = re.compile(r"[\u3400-\u9fff]")


def get_language():
    try:
        from language_settings import resolve_ui_language
        return resolve_ui_language(_language_override)
    except (ImportError, OSError, ValueError):
        code = _language_override
        if not code or code == "system":
            code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en_US")
        return "zh_CN" if str(code).lower().startswith("zh") else "en_US"


def set_language(code=None):
    """Change this process's language; persistence belongs to language_settings."""
    global _language_override
    if code not in (None, "system", "zh_CN", "en_US"):
        raise ValueError("Unsupported interface language")
    _language_override = code


def tr(english, chinese):
    return chinese if get_language() == "zh_CN" else english


# These phrases are not parallel translations, or have shortcuts/units that
# must remain visible in either language. Keep their meaning explicit.
_CATALOG = {
    "Desktop": ("Desktop", "桌面"),
    "No focused window": ("No focused window", "没有当前窗口"),
    "Unknown application": ("Unknown application", "未知应用"),
    "Focused application unavailable": ("Focused application unavailable", "当前应用不可用"),
    "Library": ("Library", "资源库"),
    "Playback": ("Playback", "播放设置"),
    "Refresh": ("Refresh", "刷新"),
    "控制中心": ("Control Center", "控制中心"),
    "Control Center": ("Control Center", "控制中心"),
    "Keyboard Atlas": ("Keyboard shortcuts", "键盘快捷键"),
    "Intelligence": ("AI assistant", "AI 助手"),
    "控制中心  ·  Your desktop, at a touch": ("Your desktop, at a touch", "常用操作，触手可及"),
    "快捷键总览  ·  Find your next move": ("Find your next move", "快速查找按键与操作"),
    "AI 侧边栏  ·  A little room to think": ("A little room to think", "随时提问与思考"),
    "总览": ("Overview", "总览"), "声音": ("Sound", "声音"),
    "系统": ("System", "系统"), "屏幕": ("Displays", "屏幕"),
    "外观": ("Appearance", "外观"),
    "Ctrl + 1…5  切换页面 · Select page": ("Ctrl + 1…5  Select page", "Ctrl + 1…5  切换页面"),
    "Ctrl + Tab  下一页 · Next page": ("Ctrl + Tab  Next page", "Ctrl + Tab  下一页"),
    "Tab / Shift + Tab  移动焦点 · Move focus": ("Tab / Shift + Tab  Move focus", "Tab / Shift + Tab  移动焦点"),
    "Space / Enter  激活 · Activate": ("Space / Enter  Activate", "空格 / Enter  激活"),
    "← →  调节滑块 · Adjust slider": ("← →  Adjust slider", "← →  调节滑块"),
    "Esc  返回总览，再关闭 · Back, then close": ("Esc  Back, then close", "Esc  返回总览，再关闭"),
    "Close · 关闭  Esc": ("Close  Esc", "关闭  Esc"),
    "Keyboard help · 键盘操作  F1": ("Keyboard help  F1", "键盘操作  F1"),
    "2 s · 每两秒": ("Every 2 seconds", "每两秒"),
    "LIVE / 实时": ("LIVE", "实时"),
    "检测中…": ("Checking…", "检测中…"),
    "没有正在播放的音乐": ("Not playing", "没有正在播放的音乐"),
    "打开播放器开始聆听": ("Open a player to listen", "打开播放器开始聆听"),
    "等待播放器响应…": ("Waiting for player…", "等待播放器响应…"),
    "从一个想法开始。": ("Start with an idea.", "从一个想法开始。"),
    "Send  ↗  发送": ("Send  ↗", "发送  ↗"),
    "Mod = Super / Windows  ·  Esc = Close / 关闭": ("Mod = Super / Windows  ·  Esc = Close", "Mod = Super / Windows  ·  Esc = 关闭"),
    "Enter to send · 回车发送   /   Shift+Enter for newline · 换行": ("Enter to send  /  Shift+Enter for newline", "Enter 发送  /  Shift+Enter 换行"),
    "Search keys or actions…  搜索按键或功能…": ("Search keys or actions…", "搜索按键或功能…"),
    "静音 / 取消静音 · Mute / Unmute": ("Mute / Unmute", "静音 / 取消静音"),
    "亮度不可用 · 在更多控制中查看原因": ("Brightness unavailable; see More controls", "亮度不可用，在更多控制中查看原因"),
    "DDC/CI · Monitor brightness / 显示器硬件亮度": ("DDC/CI · Monitor brightness", "DDC/CI · 显示器硬件亮度"),
    "API base example · API 基地址示例: https://api.openai.com/v1": ("API base example: https://api.openai.com/v1", "API 基地址示例：https://api.openai.com/v1"),
    "Ollama · 本地模型": ("Ollama · Local models", "Ollama · 本地模型"),
    "OpenAI-compatible API · 兼容 API": ("OpenAI-compatible API", "OpenAI 兼容 API"),
    "CPU · 处理器": ("CPU", "CPU 处理器"),
    "RAM · 内存": ("Memory", "内存"),
    "GPU · 显卡": ("GPU", "GPU 显卡"),
}

# Playlist, system inventory and appearance review vocabulary.
_CATALOG.update({
    '(configured)': ('(configured)', '（已配置）'),
    '20–100%. Below 40%, text edges and separators are strengthened; readability still depends on the wallpaper.': ('20–100%. Below 40%, text edges and separators are strengthened; readability still depends on the wallpaper.', '可调 20–100%。低于 40% 会加强文字边缘和分隔线；可读性仍取决于壁纸。'),
    'Add folder': ('Add folder', '添加目录'),
    'Add selected': ('Add selected', '加入所选'),
    'Add the 431960 folder, a project folder, or an image directory.': ('Add the 431960 folder, a project folder, or an image directory.', '可添加 431960 目录、单个项目目录或图片目录。'),
    'After playback ends': ('After playback ends', '播完切换'),
    'Apply wallpaper': ('Apply wallpaper', '应用壁纸'),
    'Applying wallpaper…': ('Applying wallpaper…', '正在应用壁纸…'),
    'Architecture': ('Architecture', '架构'),
    'Audio service unavailable: picture continues silently. Save sound again after audio recovers.': ('Audio service unavailable: picture continues silently. Save sound again after audio recovers.', '音频服务不可用：画面继续静音播放；音频恢复后再次保存声音即可。'),
    'Automatic wallpaper rotation': ('Automatic wallpaper rotation', '自动轮播壁纸'),
    'CPU': ('CPU', '处理器'),
    'CPU frequency': ('CPU frequency', '处理器当前频率'),
    'Cancel': ('Cancel', '取消'),
    'Choose file': ('Choose file', '选择文件'),
    'Clear playlist': ('Clear playlist', '清空播放集'),
    'Copy system information': ('Copy system information', '复制系统信息'),
    'Cores / threads': ('Cores / threads', '物理核／逻辑线程'),
    'Current wallpaper': ('Current wallpaper', '当前壁纸'),
    'Default wallpaper · static': ('Default wallpaper · static', '默认壁纸 · 静态'),
    'Desktop / WM': ('Desktop / WM', '桌面／窗口管理器'),
    'Desktop theme': ('Desktop theme', '桌面主题'),
    'Displays': ('Displays', '显示器'),
    'Distribution': ('Distribution', '发行版'),
    'Empty: rotation is idle.': ('Empty: rotation is idle.', '为空时不轮播。'),
    'Font': ('Font', '字体'),
    'GPU / driver': ('GPU / driver', '显卡／驱动'),
    'Grid': ('Grid', '网格'),
    'Host': ('Host', '主机'),
    'Icons': ('Icons', '图标主题'),
    'Image': ('Image', '图片'),
    'Images, videos or project.json': ('Images, videos or project.json', '图片、视频或 project.json'),
    'Interval (minutes, 1–180)': ('Interval (minutes, 1–180)', '间隔（分钟，1–180）'),
    'Kernel': ('Kernel', '内核'),
    'Language': ('Language', '语言'),
    'List': ('List', '列表'),
    'Live mode': ('Live mode', '实时模式 (live)'),
    'Local IP': ('Local IP', '本地 IP'),
    'Local images and Wallpaper Engine downloads': ('Local images and Wallpaper Engine downloads', '本地图片与 Wallpaper Engine 已下载壁纸'),
    'Machine': ('Machine', '机型'),
    'Mainboard': ('Mainboard', '主板'),
    'Memory': ('Memory', '内存'),
    'Mute wallpaper': ('Mute wallpaper', '静音壁纸'),
    'Next': ('Next', '下一条'),
    'Optional: Wallpaper Engine assets folder': ('Optional: Wallpaper Engine assets folder', '可选：Wallpaper Engine assets 目录'),
    'Original assets required for experimental scene/Web playback': ('Original assets required for experimental scene/Web playback', '实验性场景/网页播放需要正版原始资源；可直接粘贴路径'),
    'Packages': ('Packages', '已安装包数量'),
    'Play Web wallpaper (experimental)': ('Play Web wallpaper (experimental)', '播放网页壁纸（实验性）'),
    'Playlist': ('Playlist', '播放集'),
    'Playlist is empty.': ('Playlist is empty.', '播放集为空。'),
    'Playlist saved; rotation continues after closing this panel.': ('Playlist saved; rotation continues after closing this panel.', '播放集已保存；关闭面板后仍会自动轮播。'),
    'Preview unavailable': ('Preview unavailable', '预览不可用'),
    'Previous': ('Previous', '上一条'),
    'Random': ('Random', '随机'),
    'Reading local library…': ('Reading local library…', '正在读取本地资源库…'),
    'Reading…': ('Reading…', '读取中…'),
    'Refresh current wallpaper': ('Refresh current wallpaper', '刷新当前壁纸'),
    'Remove selected': ('Remove selected', '移出所选'),
    'Rescan': ('Rescan', '重新扫描'),
    'Root storage': ('Root storage', '根分区'),
    'Save playlist': ('Save playlist', '保存播放集'),
    'Save sound': ('Save sound', '保存声音'),
    'Scene': ('Scene', '场景'),
    'Scene · experimental backend required': ('Scene · experimental backend required', '场景 · 需要实验性播放后端'),
    'Scene/Web playback resources': ('Scene/Web playback resources', '场景/网页播放资源'),
    'Search wallpapers': ('Search wallpapers', '搜索壁纸'),
    'Select': ('Select', '选择'),
    'Sequential': ('Sequential', '顺序'),
    'Shell': ('Shell', 'Shell'),
    'Showing the first 1000 items; choose a smaller folder.': ('Showing the first 1000 items; choose a smaller folder.', '最多显示 1000 项，请缩小目录范围。'),
    'Some Steam libraries are not mounted.': ('Some Steam libraries are not mounted.', '部分 Steam 库尚未挂载。'),
    'Some metadata could not be read.': ('Some metadata could not be read.', '部分项目元数据无法读取。'),
    'Static (preview)': ('Static (preview)', '静态 (preview)'),
    'Static wallpaper only': ('Static wallpaper only', '仅支持静态壁纸'),
    'Swap': ('Swap', '交换空间'),
    'System information copied': ('System information copied', '系统信息已复制'),
    'Terminal': ('Terminal', '终端'),
    'Timed switching': ('Timed switching', '定时切换'),
    'Timezone': ('Timezone', '时区'),
    'Unavailable': ('Unavailable', '不可用'),
    'Uptime': ('Uptime', '运行时间'),
    'Use filtered library': ('Use filtered library', '使用筛选结果'),
    'Use static wallpaper': ('Use static wallpaper', '设为静态壁纸'),
    'Video': ('Video', '视频'),
    'Video · mpvpaper required': ('Video · mpvpaper required', '视频 · 需要 mpvpaper'),
    'Videos switch at their real end. Static images and endlessly running scenes/Web pages require timed switching. Changes take effect only after Save playlist.': ('Videos switch at their real end. Static images and endlessly running scenes/Web pages require timed switching. Changes take effect only after Save playlist.', '视频会在实际播完后切换。静态图片和无限运行的场景/网页请用定时切换；修改仅在保存播放集后生效。'),
    'Wallpaper changed.': ('Wallpaper changed.', '壁纸已切换。'),
    'Wallpaper saved.': ('Wallpaper saved.', '壁纸已保存。'),
    'Wallpaper sound is on by default; volume applies only to wallpaper.': ('Wallpaper sound is on by default; volume applies only to wallpaper.', '壁纸声音默认开启；此音量仅影响壁纸。'),
    'Wallpaper sound saved.': ('Wallpaper sound saved.', '壁纸声音已保存。'),
    'Web': ('Web', '网页'),
    "Web · experimental; playback executes this project's webpage scripts": ("Web · experimental; playback executes this project's webpage scripts", '网页 · 实验性；播放会执行此项目自带网页脚本'),
})


# Wallpaper playlist, display and rating labels.
_CATALOG.update({
    "Default": ("Default", "默认"),
    "Wayland display unavailable": ("Wayland display unavailable", "Wayland 显示不可用"),
    'Install in your terminal; review the AUR build and enter your sudo password there. Then Rescan.': ('Install in your terminal; review the AUR build and enter your sudo password there. Then Rescan.', '在自己的终端安装，检查构建内容并在那里输入 sudo 密码；安装后点“重新扫描”。'),
    'Install in your terminal and enter your sudo password there. Then Rescan.': ('Install in your terminal and enter your sudo password there. Then Rescan.', '在自己的终端安装并在那里输入 sudo 密码；安装后点“重新扫描”。'),
    'This project supports static wallpaper only': ('This project supports static wallpaper only', '此类项目仅支持静态壁纸'),
    'Metadata is too large': ('Metadata is too large', '元数据文件过大'),
    'Invalid wallpaper metadata': ('Invalid wallpaper metadata', '壁纸元数据无效'),
    'Invalid local path': ('Invalid local path', '本地路径无效'),
    'Wallpaper preferences exceed the 2 MB limit': ('Wallpaper preferences exceed the 2 MB limit', '壁纸偏好超过 2 MB 上限'),
    'Folder not found': ('Folder not found', '目录不存在'),
    'This project has no usable preview image; choose one with a valid preview.': ('This project has no usable preview image; choose one with a valid preview.', '此项目没有可用的预览图，请选择带有效预览图的项目。'),
    'Invalid wallpaper mode': ('Invalid wallpaper mode', '壁纸模式无效'),
    'This wallpaper is hidden by the age-rating filter': ('This wallpaper is hidden by the age-rating filter', '此壁纸被年龄分级过滤隐藏'),
    'Cannot cache wallpaper': ('Cannot cache wallpaper', '无法缓存壁纸'),
    'Invalid interrupted wallpaper transaction': ('Invalid interrupted wallpaper transaction', '中断的壁纸事务记录无效'),
    'Preserving wallpaper settings edited after interruption': ('Preserving wallpaper settings edited after interruption', '保留壁纸中断后被修改的设置'),
    'Invalid wallpaper rating': ('Invalid wallpaper rating', '壁纸分级无效'),
    'Invalid playlist direction': ('Invalid playlist direction', '播放集切换方向无效'),
    'or: ': ('or: ', '或：'),
    'At most 32 folders': ('At most 32 folders', '最多添加 32 个目录'),
    'Could not extract video preview': ('Could not extract video preview', '无法提取视频预览图'),
    'Select the original Wallpaper Engine assets folder: Steam → Wallpaper Engine → Manage → Browse local files → assets': ('Select the original Wallpaper Engine assets folder: Steam → Wallpaper Engine → Manage → Browse local files → assets', '请指定正版 Wallpaper Engine 的 assets 目录：Steam → Wallpaper Engine → 管理 → 浏览本地文件 → assets'),
    'No active Niri outputs': ('No active Niri outputs', '没有活动的 Niri 屏幕'),
    'Wallpaper changed during playlist switching; preserving the newer choice.': ('Wallpaper changed during playlist switching; preserving the newer choice.', '轮播切换期间壁纸设置已更改，保留较新的选择。'),
    'Previous selection and renderer restored.': ('Previous selection and renderer restored.', '已恢复原选择，并确认原壁纸服务运行。'),
    'Playlists changed elsewhere; reopen before saving': ('Playlists changed elsewhere; reopen before saving', '播放集已被其他操作更改，请重新打开后保存'),
    'Active playlist changed; reload before saving': ('Active playlist changed; reload before saving', '当前播放集已更改，请重新读取后保存'),
    'Up to 1000 rated wallpapers': ('Up to 1000 rated wallpapers', '最多为 1000 张壁纸设置分级'),
    'Confirm before showing Mature wallpapers': ('Confirm before showing Mature wallpapers', '显示 Mature 壁纸前需要确认'),
    'No playlist entry could be applied: ': ('No playlist entry could be applied: ', '播放集条目均无法应用：'),
    'Unknown wallpaper service action': ('Unknown wallpaper service action', '壁纸服务操作未知'),
    'Available: ': ('Available: ', '已具备：'),
    'No preview image; ffmpeg is required for video thumbnails': ('No preview image; ffmpeg is required for video thumbnails', '没有预览图；视频缩略图需要 ffmpeg'),
    'New wallpaper renderer did not become ready': ('New wallpaper renderer did not become ready', '新壁纸渲染器未就绪'),
    'Video playback requires the optional AUR package mpvpaper': ('Video playback requires the optional AUR package mpvpaper', '视频播放需要可选 AUR 软件包 mpvpaper'),
    'Scene/Web playback requires linux-wallpaperengine-git (AUR, experimental)': ('Scene/Web playback requires linux-wallpaperengine-git (AUR, experimental)', '场景/网页播放需要 linux-wallpaperengine-git（AUR，实验性支持）'),
    'Wallpaper changed; theme update failed: ': ('Wallpaper changed; theme update failed: ', '壁纸已更换；主题更新失败：'),
    'Previous wallpaper recovery failed: ': ('Previous wallpaper recovery failed: ', '原壁纸恢复失败：'),
    'New wallpaper renderer failed; keeping the previous one': ('New wallpaper renderer failed; keeping the previous one', '新壁纸渲染器失败，保留原壁纸'),
    'Fade overlay failed': ('Fade overlay failed', '淡入淡出图层失败'),
    'Optional backend missing: ': ('Optional backend missing: ', '缺少可选后端：'),
    'Wallpaper change failed: ': ('Wallpaper change failed: ', '壁纸切换失败：'),
    'Fade overlay did not become ready': ('Fade overlay did not become ready', '淡入淡出图层未就绪'),
    'Playlist name must be text': ('Playlist name must be text', '播放集名称必须是文字'),
    'Name: 1–64 letters, numbers, spaces or _-.()': ('Name: 1–64 letters, numbers, spaces or _-.()', '名称：1–64 个字母、汉字、数字、空格或 _-.()'),
    'Playlist no longer exists': ('Playlist no longer exists', '播放集已不存在'),
    'Playlist name already exists': ('Playlist name already exists', '播放集名称已存在'),
    'Up to 16 playlists': ('Up to 16 playlists', '最多 16 个播放集'),
    'Keep at least one playlist; clear it instead': ('Keep at least one playlist; clear it instead', '至少保留一个播放集；可清空其内容'),
    'Invalid playlist action': ('Invalid playlist action', '播放集操作无效'),
    'Cover and fill both crop to fill the screen.': ('Cover and fill both crop to fill the screen.', '覆盖与填充均保持比例裁切以铺满屏幕。'),
    'mpvpaper does not support tiling; using fit with black bars. The static fallback still tiles.': ('mpvpaper does not support tiling; using fit with black bars. The static fallback still tiles.', 'mpvpaper 不支持平铺；使用完整显示并允许黑边。静态兜底仍按平铺显示。'),
    'linux-wallpaperengine has no equivalent center/tile mode; using fit. Web content controls its own layout. The static fallback uses your chosen mode.': ('linux-wallpaperengine has no equivalent center/tile mode; using fit. Web content controls its own layout. The static fallback uses your chosen mode.', 'linux-wallpaperengine 无等价居中/平铺模式，使用完整显示；网页内容自行决定布局。静态兜底遵循所选模式。'),
    'Web content controls its own layout; scaling flags may not affect the page.': ('Web content controls its own layout; scaling flags may not affect the page.', '网页内容自行决定布局；缩放参数可能不影响页面。'),
    'Playlist name (1–64 characters)': ('Playlist name (1–64 characters)', '播放集名称（1–64 字）'),
    'Letters, numbers, spaces and _-.(); Save applies all playlist edits.': ('Letters, numbers, spaces and _-.(); Save applies all playlist edits.', '允许汉字、字母、数字、空格和 _-.()；保存后应用所有播放集修改。'),
    'Fade works between static wallpapers. Video, scene and Web backends switch instantly.': ('Fade works between static wallpapers. Video, scene and Web backends switch instantly.', '淡入淡出适用于静态壁纸之间；视频、场景和网页后端使用瞬间切换。'),
    'Cancel': ('Cancel', '取消'),
    'Confirm': ('Confirm', '确认'),
    'New': ('New', '新建'),
    'Rename': ('Rename', '重命名'),
    'Copy': ('Copy', '复制'),
    'Delete': ('Delete', '删除'),
    'The selected playlist becomes active after Save. Unsaved drafts are retained when switching within this panel.': ('The selected playlist becomes active after Save. Unsaved drafts are retained when switching within this panel.', '保存后，所选播放集成为当前生效的播放集；在本面板内切换会保留未保存草稿。'),
    'Playlist draft updated. Save to apply.': ('Playlist draft updated. Save to apply.', '播放集草稿已更新，请保存以应用。'),
    'Weight (1–100)': ('Weight (1–100)', '权重（1–100）'),
    'Display mode and transitions': ('Display mode and transitions', '显示模式与过渡'),
    'Fill': ('Fill', '填充'),
    'Cover': ('Cover', '覆盖'),
    'Stretch': ('Stretch', '拉伸'),
    'Fit': ('Fit', '完整显示'),
    'Center': ('Center', '居中'),
    'Tile': ('Tile', '平铺'),
    'Instant': ('Instant', '瞬间切换'),
    'Crossfade': ('Crossfade', '淡入淡出'),
    'Fade duration (seconds, 0.1–10)': ('Fade duration (seconds, 0.1–10)', '过渡时长（秒，0.1–10）'),
    'Age ratings': ('Age ratings', '年龄分级'),
    'Everyone · All ages': ('Everyone · All ages', 'Everyone · 全年龄'),
    'Questionable · Sensitive': ('Questionable · Sensitive', 'Questionable · 存疑内容'),
    'Mature · Adult content': ('Mature · Adult content', 'Mature · 成人内容'),
    'Unrated wallpapers are Everyone. Ratings are local labels, not automatic content detection.': ('Unrated wallpapers are Everyone. Ratings are local labels, not automatic content detection.', '未分级壁纸默认为 Everyone；这是本机标签，不是自动内容检测。'),
    'Wallpaper preferences saved.': ('Wallpaper preferences saved.', '壁纸偏好已保存。'),
    'Show Mature content in the library and allow it in wallpaper rotation?': ('Show Mature content in the library and allow it in wallpaper rotation?', '显示 Mature 内容，并允许播放集轮播这些壁纸？'),
    'Entry enabled': ('Entry enabled', '启用此条目'),
    'Up': ('Up', '上移'),
    'Down': ('Down', '下移'),
    'First': ('First', '置顶'),
    'Sort by name': ('Sort by name', '按名称排序'),
    'Sort by path': ('Sort by path', '按路径排序'),
    'Remove entry': ('Remove entry', '移除此条'),
    'Save display settings': ('Save display settings', '保存显示设置'),
    'Rate selected': ('Rate selected', '设置所选分级'),
    'Rate filtered library': ('Rate filtered library', '批量设置筛选结果'),
    'Show Questionable': ('Show Questionable', '显示 Questionable 内容'),
    'Show Mature (confirmation required)': ('Show Mature (confirmation required)', '显示 Mature 内容（需要确认）'),
    'Save age filter': ('Save age filter', '保存分级过滤'),
    'Search wallpapers': ('Search wallpapers', '搜索壁纸'),
    'Optional: Wallpaper Engine assets folder': ('Optional: Wallpaper Engine assets folder', '可选：Wallpaper Engine assets 目录'),
    'Original assets required for experimental scene/Web playback': ('Original assets required for experimental scene/Web playback', '实验性场景/网页播放需要正版原始资源；可直接粘贴路径'),
    'Seconds': ('Seconds', '秒'),
    'Minutes': ('Minutes', '分钟'),
    'Reading local library…': ('Reading local library…', '正在读取本地资源库…'),
    'Image': ('Image', '图片'),
    'Video · mpvpaper required': ('Video · mpvpaper required', '视频 · 需要 mpvpaper'),
    'Scene · experimental backend required': ('Scene · experimental backend required', '场景 · 需要实验性播放后端'),
    "Web · experimental; playback executes this project's webpage scripts": ("Web · experimental; playback executes this project's webpage scripts", '网页 · 实验性；播放会执行此项目自带网页脚本'),
    'Select': ('Select', '选择'),
    'Applying wallpaper…': ('Applying wallpaper…', '正在应用壁纸…'),
    'Current wallpaper': ('Current wallpaper', '当前壁纸'),
    'Reading…': ('Reading…', '读取中…'),
    'Refresh': ('Refresh', '刷新'),
    'Library': ('Library', '资源库'),
    'Playlist': ('Playlist', '播放集'),
    'Playback': ('Playback', '播放设置'),
    'Local images and Wallpaper Engine downloads': ('Local images and Wallpaper Engine downloads', '本地图片与 Wallpaper Engine 已下载壁纸'),
    'Grid': ('Grid', '网格'),
    'List': ('List', '列表'),
    'Choose file': ('Choose file', '选择文件'),
    'Add folder': ('Add folder', '添加目录'),
    'Rescan': ('Rescan', '重新扫描'),
    'Save sound': ('Save sound', '保存声音'),
    'Wallpaper sound is on by default; volume applies only to wallpaper.': ('Wallpaper sound is on by default; volume applies only to wallpaper.', '壁纸声音默认开启；此音量仅影响壁纸。'),
    'Use static wallpaper': ('Use static wallpaper', '设为静态壁纸'),
    'Apply wallpaper': ('Apply wallpaper', '应用壁纸'),
    'Sequential': ('Sequential', '顺序'),
    'Random (weighted)': ('Random (weighted)', '随机（按权重）'),
    'Shuffle without repeats': ('Shuffle without repeats', '洗牌不重复'),
    'Timed switching': ('Timed switching', '定时切换'),
    'After playback ends': ('After playback ends', '播完切换'),
    'Interval · minimum 1 second': ('Interval · minimum 1 second', '间隔 · 最小 1 秒'),
    'Videos switch at their real end. Static images and endlessly running scenes/Web pages require timed switching. Changes take effect only after Save playlist.': ('Videos switch at their real end. Static images and endlessly running scenes/Web pages require timed switching. Changes take effect only after Save playlist.', '视频会在实际播完后切换。静态图片和无限运行的场景/网页请用定时切换；修改仅在保存播放集后生效。'),
    'Save playlist': ('Save playlist', '保存播放集'),
    'Playlist saved; rotation continues after closing this panel.': ('Playlist saved; rotation continues after closing this panel.', '播放集已保存；关闭面板后仍会自动轮播。'),
    'Play Web wallpaper (experimental)': ('Play Web wallpaper (experimental)', '播放网页壁纸（实验性）'),
    'Images, videos or project.json': ('Images, videos or project.json', '图片、视频或 project.json'),
    'Scene/Web playback resources': ('Scene/Web playback resources', '场景/网页播放资源'),
    'Mute wallpaper': ('Mute wallpaper', '静音壁纸'),
    'Automatic wallpaper rotation': ('Automatic wallpaper rotation', '自动轮播壁纸'),
    'Add selected': ('Add selected', '加入所选'),
    'Remove selected': ('Remove selected', '移出所选'),
    'Use filtered library': ('Use filtered library', '使用筛选结果'),
    'Clear playlist': ('Clear playlist', '清空播放集'),
    'Previous': ('Previous', '上一条'),
    'Next': ('Next', '下一条'),
    'Wallpaper changed.': ('Wallpaper changed.', '壁纸已切换。'),
    'Playlist is empty.': ('Playlist is empty.', '播放集为空。'),
    'Default wallpaper · static': ('Default wallpaper · static', '默认壁纸 · 静态'),
    'Video': ('Video', '视频'),
    'Scene': ('Scene', '场景'),
    'Web': ('Web', '网页'),
    'Some Steam libraries are not mounted.': ('Some Steam libraries are not mounted.', '部分 Steam 库尚未挂载。'),
    'Add the 431960 folder, a project folder, or an image directory.': ('Add the 431960 folder, a project folder, or an image directory.', '可添加 431960 目录、单个项目目录或图片目录。'),
    'Showing the first 1000 items; choose a smaller folder.': ('Showing the first 1000 items; choose a smaller folder.', '最多显示 1000 项，请缩小目录范围。'),
    'Some metadata could not be read.': ('Some metadata could not be read.', '部分项目元数据无法读取。'),
    'Static wallpaper only': ('Static wallpaper only', '仅支持静态壁纸'),
    'Wallpaper sound saved.': ('Wallpaper sound saved.', '壁纸声音已保存。'),
    'Audio service unavailable: picture continues silently. Save sound again after audio recovers.': ('Audio service unavailable: picture continues silently. Save sound again after audio recovers.', '音频服务不可用：画面继续静音播放；音频恢复后再次保存声音即可。'),
    'Wallpaper saved.': ('Wallpaper saved.', '壁纸已保存。'),
    'Empty: rotation is idle.': ('Empty: rotation is idle.', '为空时不轮播。'),
    'Live mode': ('Live mode', '实时模式 (live)'),
    'Static (preview)': ('Static (preview)', '静态 (preview)'),
    'Unavailable': ('Unavailable', '不可用'),
    'Preview unavailable': ('Preview unavailable', '预览不可用'),
    'Invalid wallpaper service message': ('Invalid wallpaper service message', '壁纸服务消息无效'),
    'Untrusted wallpaper service socket': ('Untrusted wallpaper service socket', '壁纸服务套接字不可信'),
    'Wallpaper service owner mismatch': ('Wallpaper service owner mismatch', '壁纸服务所有者不匹配'),
    'Invalid wallpaper service response': ('Invalid wallpaper service response', '壁纸服务响应无效'),
    'Wallpaper service failed': ('Wallpaper service failed', '壁纸服务失败'),
    'Wallpaper service already running': ('Wallpaper service already running', '壁纸服务已在运行'),
})

def tr_legacy(value):
    """Select one language from a known, UI-owned legacy bilingual label.

    Prefer ``tr`` for new strings and formatted messages. This helper does not
    recursively inspect or translate arbitrary data after a diagnostic prefix.
    """
    if not isinstance(value, str) or not value:
        return value
    if value in _CATALOG:
        return tr(*_CATALOG[value])
    # Complete translations on separate lines are common in help paragraphs.
    if value.count("\n") == 1 and " · " not in value and "  /  " not in value:
        first, second = value.split("\n")
        if first.strip() and second.strip() and bool(_CJK.search(first)) != bool(_CJK.search(second)):
            english, chinese = (second, first) if _CJK.search(first) else (first, second)
            return tr(english, chinese)
    # Preserve any appended detail verbatim, including paths and user names.
    # A colon/newline can delimit error detail after the bilingual prefix.
    for separator in (" · ", "  /  "):
        if value.count(separator) != 1:
            continue
        first, second = value.split(separator, 1)
        tail = ""
        second_head = re.split(r"(: |：|\n)", second, maxsplit=1)
        if len(second_head) == 3:
            second, delimiter, detail = second_head
            tail = delimiter + detail
        if not first.strip() or not second.strip() or bool(_CJK.search(first)) == bool(_CJK.search(second)):
            continue
        english, chinese = (second, first) if _CJK.search(first) else (first, second)
        return tr(english.strip(), chinese.strip()) + tail
    return value


if __name__ == "__main__":
    if sys.argv[1:] == ["language"]:
        print(get_language())
    else:
        raise SystemExit("Usage: i18n.py language")
