"""Backend display capabilities and independent age-rating preferences."""
import math
import json
import stat
from functools import lru_cache
from pathlib import Path
from i18n import tr

MODES = ('fill', 'cover', 'stretch', 'fit', 'center', 'tile')
RATINGS = ('everyone', 'questionable', 'mature')
DISPLAY = {'mode': 'fill', 'transition': 'instant', 'duration': .6}
FILTER = {'everyone': True, 'questionable': False, 'mature': False, 'unrated': False}


def display(value):
    result = dict(DISPLAY)
    if isinstance(value, dict):
        if value.get('mode') in MODES:
            result['mode'] = value['mode']
        if value.get('transition') in ('instant', 'fade'):
            result['transition'] = value['transition']
        duration = value.get('duration')
        if type(duration) in (int, float) and math.isfinite(duration) and .1 <= duration <= 10:
            result['duration'] = float(duration)
    return result


def ratings(value, clean):
    result = {}
    if isinstance(value, dict) and len(value) <= 1000:
        for path, rating in value.items():
            try:
                if rating in RATINGS:
                    result[str(clean(path))] = rating
            except (OSError, ValueError, TypeError):
                pass
    return result


def rating_filter(value):
    return {key: value.get(key) if isinstance(value, dict) and type(value.get(key)) is bool else default
            for key, default in FILTER.items()}


def filter_value(choice):
    """DSH's categories are exact matches, not cumulative age limits."""
    key = 'questionable' if choice == 'pg13' else choice
    if key not in (*FILTER, 'all'):
        raise ValueError('Unknown content-rating filter')
    return {rating: key == 'all' or rating == key for rating in FILTER}


def filter_choice(value):
    value = rating_filter(value)
    for choice in ('all', 'everyone', 'pg13', 'mature', 'unrated'):
        if value == filter_value(choice):
            return choice
    return 'custom'  # Preserve saved combinations until an explicit edit.


def project_rating(value):
    if not isinstance(value, str) or len(value) > 64:
        return 'unrated'
    value = value.strip().casefold()
    if value in ('everyone', 'general', 'g'):
        return 'everyone'
    if value in ('pg13', 'pg-13', 'pg 13', 'questionable'):
        return 'questionable'
    if value in ('mature', 'adult', 'adultonly', '18+', 'r18'):
        return 'mature'
    return 'unrated'


@lru_cache(maxsize=1024)
def _project_contentrating(filename, fingerprint):
    """Bounded cache invalidated by file replacement or metadata edits."""
    try:
        if fingerprint[-1] > 2_000_000:
            return None
        with Path(filename).open('rb') as stream:
            data = stream.read(2_000_001)
        if len(data) > 2_000_000:
            return None
        value = json.loads(data.decode('utf-8-sig'))
        rating = value.get('contentrating') if isinstance(value, dict) else None
        return rating if isinstance(rating, str) and len(rating) <= 64 else None
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def rating_info(settings, path, *, item=None):
    """Use project metadata first; old local tags only apply to single files.

    GTK passes the already scanned item, so filtering and selection never read
    the disk on the UI thread. Resident rotation checks the metadata fingerprint
    and activation passes freshly revalidated project data.
    """
    if item is not None:
        project = item.get('rating_source') == 'project'
        contentrating = item.get('contentrating')
    else:
        filename = Path(path)
        project = filename.name == 'project.json' or filename.is_dir()
        contentrating = None
        if project:
            metadata = filename if filename.name == 'project.json' else filename / 'project.json'
            try:
                st = metadata.stat()
                if stat.S_ISREG(st.st_mode):
                    contentrating = _project_contentrating(str(metadata), (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size))
            except OSError:
                pass
    if project:
        return {'rating': project_rating(contentrating), 'source': 'project'}
    label = settings.get('ratings', {}).get(str(path))
    if label in RATINGS:
        return {'rating': label, 'source': 'local-label'}
    return {'rating': 'everyone', 'source': 'local'}


def allowed(settings, path, *, item=None):
    rating = rating_info(settings, path, item=item)['rating']
    return rating_filter(settings.get('rating_filter')).get(rating, False)


def sway_mode(mode):
    return 'fill' if mode == 'cover' else mode


def mpv_options(mode):
    return {
        'fill': 'panscan=1 keepaspect=yes video-unscaled=no',
        'cover': 'panscan=1 keepaspect=yes video-unscaled=no',
        'stretch': 'panscan=0 keepaspect=no video-unscaled=no',
        'fit': 'panscan=0 keepaspect=yes video-unscaled=no',
        'center': 'panscan=0 keepaspect=yes video-unscaled=yes',
        'tile': 'panscan=0 keepaspect=yes video-unscaled=no',
    }[mode]


def engine_options(mode):
    return ['--scaling', {'fill': 'fill', 'cover': 'fill', 'stretch': 'stretch', 'fit': 'fit',
                           'center': 'fit', 'tile': 'fit'}[mode], '--clamp', 'border']


def backend_name(item, mode):
    return 'swaybg' if mode == 'preview' or item['type'] == 'image' else 'mpvpaper' if item['type'] == 'video' else 'linux-wallpaperengine'


def notices(item, selection_mode, settings):
    name = backend_name(item, selection_mode)
    mode = settings['mode']
    result = []
    if mode == 'cover':
        result.append(tr('Cover and fill both crop to fill the screen.', '覆盖与填充均保持比例裁切以铺满屏幕。'))
    if name == 'mpvpaper' and mode == 'tile':
        result.append(tr('mpvpaper does not support tiling; using fit with black bars. The static fallback still tiles.',
                         'mpvpaper 不支持平铺；使用完整显示并允许黑边。静态兜底仍按平铺显示。'))
    if name == 'linux-wallpaperengine' and mode in ('center', 'tile'):
        result.append(tr('linux-wallpaperengine has no equivalent center/tile mode; using fit. Web content controls its own layout. The static fallback uses your chosen mode.',
                         'linux-wallpaperengine 无等价居中/平铺模式，使用完整显示；网页内容自行决定布局。静态兜底遵循所选模式。'))
    elif name == 'linux-wallpaperengine' and item['type'] == 'web':
        result.append(tr('Web content controls its own layout; scaling flags may not affect the page.', '网页内容自行决定布局；缩放参数可能不影响页面。'))
    if settings['transition'] == 'fade' and name != 'swaybg':
        result.append(tr(f'{name} does not support crossfade; switching instantly. Static images and previews support fade.',
                         f'{name} 不支持淡入淡出，使用瞬间切换；静态图片及静态模式支持淡入淡出。'))
    return result
