"""Daily Rust components; legacy choices migrate safely to current defaults."""
import json
import os
from pathlib import Path
import shutil
import sys
import time
from datetime import datetime,timezone
from appearance import BASE, _commit, _lock
from i18n import tr

DEFAULTS = {'bar':'eww', 'launcher':'anyrun', 'terminal':'alacritty'}
CHOICES = {kind:(value,) for kind,value in DEFAULTS.items()}
HEALTH_MAX_RECORDS = 400


def _compact_health(lines):
    """Keep recent evidence bounded while preserving the clean-stability window."""
    if len(lines) <= HEALTH_MAX_RECORDS:
        return lines
    parsed = []
    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict):
            parsed.append((raw, rec))
    if len(parsed) <= HEALTH_MAX_RECORDS:
        return [raw for raw, _ in parsed]
    # Keep the latest non-drill fallback, earliest ready entry per unique session
    # after it (so stability() retains exact clean_days and session counts), plus
    # the most recent tail.
    tail_count = HEALTH_MAX_RECORDS // 2
    keep = set(range(max(0, len(parsed) - tail_count), len(parsed)))
    failures = [i for i, (_, r) in enumerate(parsed) if r.get('event') == 'fallback' and not r.get('deliberate_drill')]
    start = failures[-1] if failures else 0
    if failures:
        keep.add(failures[-1])
    seen_sessions = set()
    for i in range(start, len(parsed)):
        rec = parsed[i][1]
        if rec.get('event') == 'eww-ready' and isinstance(rec.get('session'), str) and not rec.get('deliberate_drill'):
            if rec['session'] not in seen_sessions:
                seen_sessions.add(rec['session'])
                keep.add(i)
    return [parsed[i][0] for i in sorted(keep)]


def health(event, detail=''):
    """Durable session evidence; a component restart is not another login."""
    log=path().parent/'component-health.jsonl'
    record={'time':datetime.now(timezone.utc).isoformat(),'event':event,'detail':str(detail)[:1000]}
    try:
        import session_identity
        pid,uid,_=session_identity.peer(os.environ['NIRI_SOCKET'])
        start=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        record['session']=f'{boot}:{pid}:{start}';record['uid']=uid
    except (OSError,ValueError,KeyError):record['session']=None
    try:
        marker=json.loads((log.parent/'component-drill.json').read_text())
        record['deliberate_drill']=isinstance(marker,dict) and marker.get('until',0)>time.time()
    except (OSError,ValueError,TypeError):record['deliberate_drill']=False
    try:
        with _lock(log):
            if log.is_symlink():
                raise OSError('Refusing to write symlink health log')
            line = json.dumps(record, ensure_ascii=False)
            existing = log.read_text(errors='replace').splitlines() if log.exists() else []
            existing.append(line)
            if len(existing) > HEALTH_MAX_RECORDS:
                existing = _compact_health(existing)
                _commit({log: ('\n'.join(existing) + '\n').encode()})
            else:
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open('a', encoding='utf-8') as stream:
                    stream.write(line + '\n')
                    stream.flush()
    except (OSError,RuntimeError) as error:
        print(tr('Component evidence could not be saved: ','组件证据无法保存：')+str(error),file=sys.stderr)


def stability():
    records=[];log=path().parent/'component-health.jsonl'
    try:
        for line in log.read_text().splitlines():
            try:
                record=json.loads(line)
                if isinstance(record,dict) and not record.get('deliberate_drill'):records.append(record)
            except ValueError:continue
    except OSError:pass
    # Reset observations at each involuntary fallback; restarts of a session
    # are deduplicated. The calendar window cannot be replaced with smoke runs.
    failures=[i for i,r in enumerate(records) if r.get('event')=='fallback']
    clean=records[(failures[-1]+1 if failures else 0):]
    ready=[r for r in clean if r.get('event')=='eww-ready' and r.get('session')]
    sessions={r['session'] for r in ready if isinstance(r['session'],str)}
    try:days=(datetime.now(timezone.utc)-datetime.fromisoformat(ready[0]['time'])).total_seconds()/86400
    except (ValueError,KeyError,IndexError,TypeError):days=0
    return {'ready':len(sessions)>=10 and days>=7,'successful_logins':len(sessions),
            'clean_days':round(max(0,days),3),'required_logins':10,'required_days':7,
            'last_failure':records[failures[-1]] if failures else None}


def path():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'selandia-niri/components.json'


def load():
    try:
        raw = json.loads(path().read_text())
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw,dict):raw={}
    return {key:raw.get(key) if raw.get(key) in choices else DEFAULTS[key] for key,choices in CHOICES.items()}


def effective(kind, settings=None, which=shutil.which):
    selected = (settings or load())[kind]
    if which(selected) and (selected != 'anyrun' or which('anyrun-provider')):
        return selected
    command = 'paru -S --needed eww anyrun' if kind != 'terminal' else 'sudo pacman -S --needed alacritty'
    raise RuntimeError(tr('Required component unavailable: ', '必需组件不可用：') + selected
                       + tr('. Install: ', '。安装：') + command)


def choose(kind, value, *, restart=True):
    if kind not in CHOICES or value not in CHOICES[kind]:raise ValueError('component')
    return choose_many({kind:value},restart=restart)


def choose_many(updates, *, restart=True):
    if not updates or any(key not in CHOICES or value not in CHOICES[key] for key,value in updates.items()):raise ValueError('component')
    import session_identity
    socket=os.environ.get('NIRI_SOCKET') if restart and 'bar' in updates else None
    owner=session_identity.peer(socket) if socket else None
    preference = path()
    with _lock(preference):
        old = preference.read_bytes() if preference.exists() else None
        values = load();values.update(updates)
        _commit({preference:(json.dumps(values,indent=2)+'\n').encode()})
    if restart and 'bar' in updates:
        import reload_components
        try:
            reload_components.service('waybar','reset-failed')
            reload_components.service('waybar','restart')
            tools_dir = str(BASE.parent / 'tools')
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            from live_update import verify_components
            verify_components(reload_components,['waybar'])
            if socket and effective('bar',values)=='eww':
                import bar_backend
                deadline=time.monotonic()+20
                info=Path(os.environ.get('XDG_RUNTIME_DIR','/run/user/'+str(os.getuid())))/'selandia-eww-runtime.json'
                while time.monotonic()<deadline:
                    try:
                        data=json.loads(info.read_text())
                        if data.get('ready') and bar_backend.bridge_alive():break
                    except (OSError,ValueError):pass
                    time.sleep(.1)
                else:raise RuntimeError(tr('Eww did not become ready; restored previous components','Eww 未就绪，已恢复之前的组件'))
            if socket and owner != session_identity.peer(socket):raise RuntimeError('compositor identity changed')
        except BaseException:
            with _lock(preference):
                # A concurrent user preference change wins over this rollback.
                if load()==values:
                    if old is None:preference.unlink(missing_ok=True)
                    else:_commit({preference:old})
            reload_components.service('waybar','restart')
            raise
    return values




def daily(*, restart=True):
    return choose_many(DEFAULTS,restart=restart)


def toggle_bar():
    import reload_components
    if reload_components.active('waybar'):
        reload_components.service('waybar','stop')
    else:
        reload_components.service('waybar','reset-failed')
        reload_components.service('waybar','start')


def terminal_command(arguments, *, settings=None, which=shutil.which):
    engine = effective('terminal',settings,which)
    # Preserve literal command argv and window metadata.
    args=list(arguments);flags=[];command=[];index=0
    while index<len(args):
        value=args[index]
        if value=='--':command=args[index+1:];break
        if value=='--config':index+=2;continue
        if value in ('--title','--class'):
            if index+1>=len(args):raise ValueError(value)
            flags += [value,args[index+1]];index+=2;continue
        if value=='--hold':flags.append(value);index+=1;continue
        command=args[index:];break
    return [engine,'--config-file',str(BASE/'theme/alacritty.toml'),*flags,*(['--command',*command] if command else [])]


def launch():
    engine=effective('launcher')
    command=[engine,'--config-dir',str(BASE/'anyrun')]
    os.execvp(command[0],command)


if __name__=='__main__':
    try:
        if sys.argv[1:2] == ['daily']:
            sys.path.insert(0,str(BASE.parent/'tools'))
            operation=daily
            print(json.dumps(operation(restart=bool(os.environ.get('NIRI_SOCKET')))))
        elif sys.argv[1:2]==['toggle-bar']:toggle_bar()
        elif sys.argv[1:2]==['stability']:print(json.dumps(stability(),ensure_ascii=False,indent=2))
        elif sys.argv[1:2]==['launcher']:launch()
        elif sys.argv[1:2]==['terminal']:
            command=terminal_command(sys.argv[2:]);os.execvp(command[0],command)
        elif len(sys.argv)==3:
            sys.path.insert(0,str(BASE.parent/'tools'));print(json.dumps(choose(sys.argv[1],sys.argv[2],restart=bool(os.environ.get('NIRI_SOCKET')))))
        else:raise ValueError('arguments')
    except (OSError,ValueError,RuntimeError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
