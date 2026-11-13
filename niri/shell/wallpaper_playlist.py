"""Validated playlist data and service scheduling, independent of GTK."""
from copy import deepcopy
import random
import re
import uuid
from i18n import tr

DEFAULTS = {'enabled': False, 'items': [], 'order': 'sequential', 'trigger': 'timer',
            'minutes': 10, 'seconds': 600, 'cycle': []}
MAX_LISTS = 16


def name(value):
    if not isinstance(value, str):
        raise ValueError(tr('Playlist name must be text', '播放集名称必须是文字'))
    value = value.strip()
    if not 1 <= len(value) <= 64 or not all(c.isalnum() or c in ' _-.()' for c in value):
        raise ValueError(tr('Name: 1–64 letters, numbers, spaces or _-.()', '名称：1–64 个字母、汉字、数字、空格或 _-.()'))
    return value


def identity(item):
    return (item.get('path'), item.get('mode'))


def validate(value, clean):
    """Bad new fields never discard valid legacy entries or other preferences."""
    result = deepcopy(DEFAULTS)
    if not isinstance(value, dict):
        return result
    items = value.get('items', [])
    if isinstance(items, list) and len(items) <= 1000:
        seen = set()
        for item in items:
            try:
                if not isinstance(item, dict) or item.get('mode') not in ('live', 'preview'):
                    continue
                entry = {'path': str(clean(item['path'])), 'mode': item['mode'],
                         'enabled': item.get('enabled') if type(item.get('enabled')) is bool else True,
                         'weight': item.get('weight') if type(item.get('weight')) is int and 1 <= item['weight'] <= 100 else 1}
                if identity(entry) not in seen:
                    result['items'].append(entry); seen.add(identity(entry))
            except (KeyError, OSError, ValueError, TypeError):
                continue
    result['enabled'] = value.get('enabled') if type(value.get('enabled')) is bool else False
    for key, allowed in (('order', ('sequential', 'random', 'shuffle')), ('trigger', ('timer', 'finished'))):
        if value.get(key) in allowed:
            result[key] = value[key]
    minutes = value.get('minutes')
    if type(minutes) is int and 1 <= minutes <= 180:
        result['minutes'], result['seconds'] = minutes, minutes * 60
    seconds = value.get('seconds')
    if type(seconds) is int and 1 <= seconds <= 10800:
        result['seconds'] = seconds
        result['minutes'] = max(1, (seconds + 59) // 60)  # Legacy projection.
    cycle = value.get('cycle')
    if isinstance(cycle, list) and len(cycle) <= 1000:
        available = {identity(item) for item in result['items'] if item['enabled']}
        seen = set()
        for item in cycle:
            if isinstance(item, dict) and isinstance(item.get('path'), str) and isinstance(item.get('mode'), str) and identity(item) in available and identity(item) not in seen:
                result['cycle'].append({'path': item['path'], 'mode': item['mode']}); seen.add(identity(item))
    return result


def registry(value, legacy, clean):
    fallback = {'version': 1, 'active': 'default', 'lists': [
        {'id': 'default', 'name': 'Default', 'settings': validate(legacy, clean)}]}
    if not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != 1:
        return fallback
    lists = value.get('lists')
    if not isinstance(lists, list) or not 1 <= len(lists) <= MAX_LISTS:
        return fallback
    result, seen, names = [], set(), set()
    for entry in lists:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', entry['id']):
            continue
        identifier = entry['id']
        if identifier in seen or not isinstance(entry.get('settings'), dict):
            continue
        try:
            title = name(entry.get('name'))
        except ValueError:
            title = 'Default'
        suffix = 1
        while title.casefold() in names:
            title = 'Default ' + str(suffix); suffix += 1
        settings = entry['settings']
        if not isinstance(settings.get('items'), list) or len(settings['items']) > 1000:
            if identifier != value.get('active'): continue
            settings = legacy
        result.append({'id': identifier, 'name': title, 'settings': validate(settings, clean)})
        seen.add(identifier); names.add(title.casefold())
    if not result or not isinstance(value.get('active'), str) or value.get('active') not in seen:
        return fallback
    return {'version': 1, 'active': value['active'], 'lists': result}


def current(value):
    return next(entry for entry in value['lists'] if entry['id'] == value['active'])


def with_current(value, settings):
    result = deepcopy(value)
    current(result)['settings'] = deepcopy(settings)
    return result


def configuration(value):
    result = deepcopy(value)
    for entry in result['lists']:
        entry['settings'].pop('cycle', None)
    return result


def merge_cycles(value, latest):
    result = deepcopy(value)
    lookup = {entry['id']: entry for entry in latest['lists']}
    for entry in result['lists']:
        old = lookup.get(entry['id'])
        if old:
            before, after = deepcopy(old['settings']), deepcopy(entry['settings'])
            before.pop('cycle', None); after.pop('cycle', None)
            if before == after: entry['settings']['cycle'] = deepcopy(old['settings']['cycle'])
    return result


def manage(value, action, *, title=None, identifier=None):
    result = deepcopy(value)
    entry = current(result) if identifier is None else next((entry for entry in result['lists'] if entry['id'] == identifier), None)
    if entry is None:
        raise ValueError(tr('Playlist no longer exists', '播放集已不存在'))
    if action in ('create', 'rename', 'duplicate'):
        title = name(title)
        if any(other['name'].casefold() == title.casefold() and (action != 'rename' or other is not entry) for other in result['lists']):
            raise ValueError(tr('Playlist name already exists', '播放集名称已存在'))
    if action in ('create', 'duplicate'):
        if len(result['lists']) >= MAX_LISTS:
            raise ValueError(tr('Up to 16 playlists', '最多 16 个播放集'))
        created = {'id': uuid.uuid4().hex, 'name': title,
                   'settings': deepcopy(DEFAULTS if action == 'create' else entry['settings'])}
        created['settings']['cycle'] = []
        result['lists'].append(created); result['active'] = created['id']
    elif action == 'rename':
        entry['name'] = title
    elif action == 'delete':
        if len(result['lists']) == 1:
            raise ValueError(tr('Keep at least one playlist; clear it instead', '至少保留一个播放集；可清空其内容'))
        result['lists'].remove(entry)
        if result['active'] == entry['id']:
            result['active'] = result['lists'][0]['id']
    elif action == 'select':
        result['active'] = entry['id']
    else:
        raise ValueError(tr('Invalid playlist action', '播放集操作无效'))
    return result


def edit(items, action, index=0, *, value=None, title=lambda item: item['path']):
    result = deepcopy(items)
    if action == 'clear':
        return []
    if action in ('sort-name', 'sort-path'):
        return sorted(result, key=lambda item: (title(item) if action == 'sort-name' else item['path']).casefold())
    if type(index) is not int or not 0 <= index < len(result):
        return result
    if action == 'remove':
        result.pop(index)
    elif action in ('up', 'down', 'top'):
        target = 0 if action == 'top' else max(0, min(len(result) - 1, index + (-1 if action == 'up' else 1)))
        result.insert(target, result.pop(index))
    elif action == 'enabled' and type(value) is bool:
        result[index]['enabled'] = value
    elif action == 'weight' and type(value) is int and 1 <= value <= 100:
        result[index]['weight'] = value
    return result


def eligible(playlist, allowed=lambda item: True):
    return [item for item in playlist['items'] if item.get('enabled', True) and allowed(item)]


def candidates(playlist, selection, direction=1, *, choose=None, allowed=lambda item: True):
    items = eligible(playlist, allowed)
    if not items:
        return []
    current_id = identity(selection) if selection else None
    if playlist['order'] == 'shuffle' and direction > 0:
        lookup = {identity(item): item for item in items}
        remaining = [lookup[identity(item)] for item in playlist.get('cycle', []) if identity(item) in lookup]
        if remaining:
            return remaining
        remaining = list(items)
        random.shuffle(remaining)
        if len(remaining) > 1 and identity(remaining[0]) == current_id:
            remaining[0], remaining[-1] = remaining[-1], remaining[0]
        return remaining
    if playlist['order'] == 'random' and direction > 0:
        remaining = [item for item in items if identity(item) != current_id]
        ordered = []
        while remaining:
            item = choose(remaining) if choose else random.choices(remaining, weights=[entry.get('weight', 1) for entry in remaining], k=1)[0]
            ordered.append(item); remaining.remove(item)
        return ordered or list(items)
    index = next((index for index, item in enumerate(items) if identity(item) == current_id), -1 if direction > 0 else 0)
    return [items[(index + direction * offset) % len(items)] for offset in range(1, len(items) + 1)]


def consume(playlist, ordered, index, direction):
    result = deepcopy(playlist)
    if result['order'] == 'shuffle' and direction > 0:
        result['cycle'] = [{'path': item['path'], 'mode': item['mode']} for item in ordered[index + 1:]]
    return result


class Schedule:
    def __init__(self, now):
        self.changed_at = now
        self.key = None
        self.retry_at = 0

    def due(self, settings, now, *, finished=False, allowed=lambda item: True):
        playlist = settings['playlist']
        key = (repr(settings['selection']), repr(playlist), repr(settings.get('rating_filter')), repr(settings.get('ratings')))
        if key != self.key:
            self.key, self.changed_at = key, now
        if not playlist['enabled'] or not eligible(playlist, allowed) or now < self.retry_at:
            return False
        interval = playlist.get('seconds', playlist['minutes'] * 60)
        return now - self.changed_at >= interval if playlist['trigger'] == 'timer' else finished

    def attempted(self, now, success):
        self.changed_at = now
        self.retry_at = now + (0 if success else 30)
