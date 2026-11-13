#!/usr/bin/env python3
"""Event bridge for Eww; existing audio/brightness/MPRIS backends own controls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
import html
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import select
import socket
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse,unquote
from appearance import BASE,load_settings
from niri_events import DesktopFeed, request as niri_request
from i18n import tr
from eww_input import clean_environment
_environment=clean_environment();os.environ.clear();os.environ.update(_environment)


def endpoint():
    identity=os.environ.get('NIRI_SOCKET') or os.environ.get('WAYLAND_DISPLAY','default')
    return Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/('selandia-island-'+hashlib.sha256(identity.encode()).hexdigest()[:20]+'.sock')


def send(action, **values):
    path=endpoint()
    try:
        info=path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():return False
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as stream:
            stream.settimeout(.25)
            stream.sendto(json.dumps({'action':action,**values}).encode(),str(path))
        return True
    except OSError:return False


def percent(value):
    result=float(value)
    if not math.isfinite(result) or not 0<=result<=100:raise ValueError('percentage')
    return round(result,1)


class Events:
    def __init__(self):
        self.kind='idle';self.until=0;self.details={};self.tray=False;self.notification_id=None
        self.media_dismissed=False

    def receive(self,value,now):
        if not isinstance(value,dict):return
        action=value.get('action')
        if action=='dismiss':
            self.kind='idle';self.until=0;self.tray=False;self.media_dismissed=True;return
        if action=='tray':self.tray=not self.tray;self.kind='tray';self.until=now+12;return
        if action=='show':
            kind=value.get('kind')
            if kind not in ('volume','brightness','media'):return
            if kind=='media':self.media_dismissed=False
            self.kind=kind;self.until=now+6;return
        if action=='notification-close':
            if self.kind=='notification' and self.notification_id==value.get('notification_id'):
                self.kind='idle';self.until=0;self.details={};self.notification_id=None
            return
        if action=='notification':
            duration=value.get('duration',8)
            if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:duration=8
            self.kind='notification';self.until=now+min(duration,8)
            self.notification_id=value.get('notification_id')
            self.details={'title':' '.join(str(value.get('title','')).split())[:160], 'summary':' '.join(html.unescape(re.sub(r'<[^>]*>','',str(value.get('summary','')))).split())[:320], 'notification_icon':value.get('icon') if isinstance(value.get('icon'),str) and re.fullmatch(r'[\w.-]{1,100}',value['icon']) else 'dialog-information-symbolic'}

    def current(self,now,playing):
        if not playing:self.media_dismissed=False
        if now<self.until:return self.kind
        self.tray=False
        return 'media' if playing and not self.media_dismissed else 'idle'


def call(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=4,env=dict(os.environ,LC_ALL='C.UTF-8'))
    if result.returncode:raise RuntimeError(result.stderr[-300:])
    return result.stdout


def visible_workspaces(workspaces, output, count):
    items=sorted((item for item in workspaces if item.get('output')==output),key=lambda item:item['idx'])
    active=next((index for index,item in enumerate(items) if item.get('is_active')),0)
    start=max(0,min(active-count//2,len(items)-count))
    return [{'id':item['id'],'name':str(item.get('name') or item['idx'])[:12],
             'active':bool(item.get('is_active'))} for item in items[start:start+count]]


@lru_cache(maxsize=128)
def application_name(app_id):
    """Resolve desktop names without executing their commands or expanding markup."""
    try:
        from gi.repository import Gio
        try:
            import gi
            gi.require_version('GioUnix','2.0')
            from gi.repository import GioUnix
            desktop=GioUnix.DesktopAppInfo
        except (ImportError,ValueError):desktop=Gio.DesktopAppInfo
        app=desktop.new(app_id if app_id.endswith('.desktop') else app_id+'.desktop')
        if app:return app.get_display_name()
        for entry in Gio.AppInfo.get_all():
            if (entry.get_id() or '').removesuffix('.desktop').casefold()==app_id.casefold() or (
                    isinstance(entry,desktop) and (entry.get_startup_wm_class() or '').casefold()==app_id.casefold()):
                return entry.get_display_name()
    except (ImportError,TypeError,RuntimeError):pass
    return app_id.rsplit('.',1)[-1] or app_id


def focused_application(window):
    def plain(value,limit):
        return ' '.join(''.join(c for c in value if c.isprintable() or c.isspace()).split())[:limit] if isinstance(value,str) else ''
    if not isinstance(window,dict):
        return {'app_name':tr('Desktop','桌面'),'window_title':tr('No focused window','没有当前窗口'),'app_id':'','window_id':None}
    app_id=plain(window.get('app_id'),160);title=plain(window.get('title'),512)
    name=plain(application_name(app_id),160) if app_id else ''
    return {'app_name':name or title or tr('Unknown application','未知应用'),
            'window_title':title or name or tr('Unknown application','未知应用'),
            'app_id':app_id,'window_id':window.get('id')}


def desktop_values(snapshot, outputs):
    if not snapshot['available']:
        return dict(desktop_available=False,app_name=tr('Unavailable','不可用'),window_title=tr('Focused application unavailable','当前应用不可用'),app_id='',window_id=None,
                    workspaces={key:[] for key in outputs})
    return {'desktop_available':True,**focused_application(snapshot['window']),
            'workspaces':{key:visible_workspaces(snapshot['workspaces'],key,5 if (data.get('logical') or {}).get('width',0)>=1300 else 3)
                          for key,data in outputs.items()}}


def sample_audio():
    values={}
    try:
        volume=re.search(r'(\d+)%',call(['pactl','get-sink-volume','@DEFAULT_SINK@']))
        mute=call(['pactl','get-sink-mute','@DEFAULT_SINK@']).strip()
        if not volume or mute not in ('Mute: yes','Mute: no'):raise ValueError('audio state')
        values.update(volume=int(volume.group(1)),has_audio=True,muted=mute=='Mute: yes')
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):values.update(has_audio=False,volume=0,muted=False)
    return values


def sample_media():
    values={'media':False,'playing':False,'player':'','title':'','cover':'',
            'can_next':False,'can_previous':False,'can_toggle':False}
    selected=None
    try:
        import media_backend
        state=media_backend.read_state();selected=state['selected']
        values.update(media=bool(selected),playing=bool(selected and selected['status']=='Playing'),
                      player=selected['id'] if selected else '',title=selected['title'] or selected['identity'] if selected else '',
                      cover='',progress=0,has_progress=False)
        values.update(can_next=bool(selected and selected['can_next']),can_previous=bool(selected and selected['can_previous']),
                      can_toggle=bool(selected and selected['can_pause' if selected['status']=='Playing' else 'can_play']))
        if selected:
            parsed=urlparse(selected['art_url']);cover=Path(unquote(parsed.path))
            if parsed.scheme=='file' and parsed.netloc in ('','localhost') and cover.is_file() and cover.stat().st_size<=20*1024*1024:values['cover']=str(cover)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):pass
    return values,selected


def sample_battery():
    values={}
    battery=next(Path('/sys/class/power_supply').glob('BAT*/capacity'),None)
    try:values['battery']=battery.read_text().strip()+'%' if battery else ''
    except OSError:values['battery']=''
    return values


def sample_brightness():
    import brightness
    data = brightness.read_state()
    device = next((item for item in data['devices'] if item['available']), None)
    return {'has_brightness': bool(device), 'brightness': device['percent'] if device else 0,
            'brightness_id': device['id'] if device else ''}


def metrics_values(data):
    """Turn MetricsSampler output into compact, localized bar strings."""
    from metrics import format_bytes, format_rate
    cpu=data.get('cpu_percent'); memory=data.get('memory') or {}; network=data.get('network') or {}
    temperatures=[item for item in (data.get('temperatures') or []) if item.get('celsius') is not None]
    hottest=max(temperatures,key=lambda item:item['celsius']) if temperatures else None
    cpu_temp=next((item for item in temperatures
                   if any(token in str(item.get('name','')).lower()
                          for token in ('cpu','package','tctl','core'))),None)
    display_temp=cpu_temp or hottest
    gpus=data.get('gpus') or []
    measured=[item for item in gpus if item.get('percent') is not None]
    gpu=max(measured,key=lambda item:item['percent']) if measured else (gpus[0] if gpus else None)
    down=network.get('down_bps'); up=network.get('up_bps'); interface=network.get('interface') or ''
    memory_percent=memory.get('percent')
    gpu_detail=('GPU ' + str(gpu.get('name') or '') +
                (f" {gpu.get('percent'):.0f}%" if gpu and gpu.get('percent') is not None else ' —%') +
                (f" · {gpu.get('temperature'):.0f}°C" if gpu and gpu.get('temperature') is not None else '')) if gpu else 'GPU —'
    return {
        'cpu_text': f'{cpu:.0f}%' if cpu is not None else '—',
        'memory_text': f'{memory_percent:.0f}%' if memory_percent is not None else '—',
        'network_text': (f'↓{format_rate(down)} ↑{format_rate(up)}'
                         if down is not None or up is not None else '—'),
        'temperature_text': f"{display_temp['celsius']:.0f}°C" if display_temp else '—',
        'gpu_text': (f"{gpu.get('percent'):.0f}%" if gpu and gpu.get('percent') is not None
                     else f"{gpu.get('temperature'):.0f}°C" if gpu and gpu.get('temperature') is not None else '—'),
        'metrics_available': any(value is not None for value in (cpu, memory_percent)),
        'metrics_detail': ' · '.join(part for part in (
            f"CPU {cpu:.0f}%" if cpu is not None else 'CPU —',
            (f"RAM {memory_percent:.0f}% ({format_bytes(memory.get('used'))} / {format_bytes(memory.get('total'))})"
             if memory_percent is not None else 'RAM —'),
            (f"NET {interface or '—'} ↓{format_rate(down)} ↑{format_rate(up)}"),
            (f"TEMP {display_temp['name']} {display_temp['celsius']:.0f}°C" if display_temp else 'TEMP —'),
            gpu_detail) if part),
    }


def listen():
    path=endpoint();stopping=threading.Event();events=queue.Queue();policy=Events()
    def stop(*_):stopping.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    stream=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    if path.exists():
        info=path.lstat()
        if info.st_uid!=os.getuid() or not stat.S_ISSOCK(info.st_mode):raise RuntimeError('untrusted island socket')
        # A live bridge must never be silently replaced.
        probe=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        try:probe.sendto(b'{}',str(path));raise RuntimeError('island bridge already active')
        except ConnectionRefusedError:path.unlink()
        finally:probe.close()
    stream.bind(str(path));os.chmod(path,0o600);stream.setblocking(False)
    from notification_events import NotificationFeed
    monitor=NotificationFeed(events,stopping,base=BASE);monitor.thread.start()
    state={'kind':'idle','width':96,'open':False,'title':'','summary':'','cover':'','can_next':False,'can_previous':False,'can_toggle':False,'media':False,'playing':False,
           'player':'','progress':0,'has_progress':False,'volume':0,'has_audio':False,'muted':False,'brightness':0,
           'has_brightness':False,'notification_icon':'dialog-information-symbolic','clock':'','clock_short':'','clock_time':'','clock_date':'',**focused_application(None),'workspaces':{},'network':'','battery':'','reduced':False,'tray':False,
           'cpu_text':'—','memory_text':'—','network_text':'—','temperature_text':'—','gpu_text':'—',
           'metrics_detail':'', 'metrics_available':False}
    from metrics import MetricsSampler
    sampler=MetricsSampler(detailed=False, enable_nvidia=False)
    sampler.prime()
    # A short deliberate warmup makes the first bar values real rates instead of
    # a dash; this runs once before the event loop, not every frame.
    time.sleep(.18)

    def sample_metrics():
        return metrics_values(sampler.sample())
    state.update(sample_metrics())
    from audio_events import AudioChanges
    from media_events import MediaChanges,RefreshGate,PlaybackClock
    audio_changes=AudioChanges(stopping);media_changes=MediaChanges(stopping)
    audio_gate=RefreshGate(audio_changes.changed);media_gate=RefreshGate(media_changes.changed)
    battery_gate=RefreshGate(interval=30);metrics_gate=RefreshGate(interval=2);playback=PlaybackClock()
    # Only an explicit brightness preview requests this potentially slow DDC read.
    brightness_gate=RefreshGate(interval=float('inf'));brightness_gate.changed.clear()
    brightness_gate.fallback=float('inf')
    audio_changes.thread.start();media_changes.thread.start()
    last='';previous_audio=None;settings_at=0;snapshot_at=0;title_at=0;progress_at=0
    last_frame=time.monotonic();frame_interval=1/120;width_tau=.055
    try:monitors=niri_request('Outputs')
    except (OSError,ValueError,RuntimeError):monitors={}
    feed=DesktopFeed(stopping);feed.thread.start()
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            while not stopping.is_set():
                now=time.monotonic()
                try:
                    value=json.loads(stream.recv(8192));
                    if isinstance(value,dict):events.put(value)
                except BlockingIOError:pass
                except ValueError:pass
                while not events.empty():
                    value=events.get_nowait();policy.receive(value,now)
                    if value.get('action') in ('show','tray','dismiss'):settings_at=0
                    if value.get('action')=='show' and value.get('kind')=='volume':audio_changes.changed.set()
                    if value.get('action')=='show' and value.get('kind')=='media':media_changes.changed.set()
                    if value.get('action')=='show' and value.get('kind')=='brightness':
                        brightness_gate.changed.set()
                    if value.get('action') in ('light-state','notification-policy'):state.update(value['values'])
                for name,gate,function in (('audio',audio_gate,sample_audio),('media',media_gate,sample_media),('battery',battery_gate,sample_battery),('metrics',metrics_gate,sample_metrics),('brightness',brightness_gate,sample_brightness)):
                    try:
                        values=gate.take()
                        if values is not None:
                            if name=='media':
                                values,player=values;playback.set(player);progress_at=0
                                state['media_title']=values.get('title','')
                            if name=='audio':
                                current_audio=(values['volume'],values['muted']) if values.get('has_audio') else None
                                if current_audio is not None and previous_audio is not None and current_audio!=previous_audio:
                                    policy.receive({'action':'show','kind':'volume'},now)
                                previous_audio=current_audio
                            state.update(values)
                    except Exception as error:print(str(error),file=sys.stderr)
                    gate.start(now,pool,function)
                if now>=progress_at:
                    state.update(playback.values(now));progress_at=now+1
                desktop=desktop_values(feed.snapshot(),monitors)
                # Terminal progress often rewrites titles many times per second.
                # Preserve immediate focus changes; coalesce a window's tooltip.
                same_window=(desktop['window_id'],desktop['app_id'],desktop['desktop_available'])==(state['window_id'],state['app_id'],state.get('desktop_available',False))
                if same_window and now<title_at:
                    desktop['window_title']=state['window_title'];desktop['app_name']=state['app_name']
                elif desktop['window_title']!=state['window_title'] or not same_window:
                    title_at=now+1
                state.update(desktop)
                if now>=settings_at:
                    state['reduced']=load_settings()['reduced_motion'];settings_at=now+1
                kind=policy.current(now,state['playing']);state.update(kind=kind,open=kind!='idle',tray=policy.tray)
                if kind=='notification':state.update(policy.details)
                elif kind=='media':state['title']=state.get('media_title','')
                elif kind in ('volume','brightness'):
                    state['title']=tr('Volume','音量') if kind=='volume' else tr('Brightness','亮度')
                    if not state['has_audio' if kind=='volume' else 'has_brightness']:state['title']+=' · '+tr('Unavailable','不可用')
                    elif kind=='volume' and state['muted']:state['title']+=' · '+tr('Muted','已静音')
                    else:state['title']+=' · '+str(round(state[kind]))+'%'
                target=460 if state['open'] else 96
                if state['reduced']:
                    state['width']=target
                else:
                    # Time-based smoothing keeps the same perceived duration on
                    # 60/120/144 Hz panels instead of stepping once per 40 ms.
                    elapsed=max(0.0,min(.05,now-last_frame))
                    alpha=1-math.exp(-elapsed/width_tau)
                    state['width']=round(state['width']+(target-state['width'])*alpha)
                    if abs(state['width']-target)<=3:state['width']=target
                last_frame=now
                clock=datetime.now();state.update(clock=clock.strftime('%a %m.%d %H:%M'),clock_short=clock.strftime('%H:%M'),
                    clock_time=clock.strftime('%H:%M'),
                    clock_date=tr(clock.strftime('%a %m.%d'), f"{clock.month}月{clock.day}日 · 周{'一二三四五六日'[clock.weekday()]}"))
                state.update(bridge_pid=os.getpid(),heartbeat=int(now))
                encoded=json.dumps(state,ensure_ascii=False)
                # Heartbeats belong to the supervisor snapshot, not the UI stream:
                # changing them made Eww re-evaluate every binding once a second.
                visible=json.dumps({key:value for key,value in state.items() if key not in ('bridge_pid','heartbeat')},ensure_ascii=False)
                changed=visible!=last
                if changed:
                    print(visible,flush=True);last=visible
                if changed or now>=snapshot_at:
                    snapshot=path.with_suffix('.json');temporary=snapshot.with_suffix('.partial');temporary.write_text(encoded);temporary.replace(snapshot)
                    snapshot_at=now+2
                # A bounded local snapshot lets controls pin the displayed player/device.
                select.select([stream],[],[],frame_interval if state['width']!=target else .25)
        finally:
            stream.close();path.unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)
            stopping.set();monitor.close();monitor.thread.join(timeout=3);feed.thread.join(timeout=2)
            audio_changes.close();media_changes.close()
            audio_changes.thread.join(timeout=3);media_changes.thread.join(timeout=3)


def main():
    action=sys.argv[1]
    if action=='listen':listen();return
    if action=='show':
        if len(sys.argv)!=3 or sys.argv[2] not in ('volume','brightness','media'):raise ValueError('show kind')
        return 0 if send('show',kind=sys.argv[2]) else 1
    if action in ('dismiss','tray'):send(action);return
    if action=='workspace':
        niri_request({'Action':{'FocusWorkspace':{'reference':{'Id':int(sys.argv[2])}}}});return
    state=json.loads(endpoint().with_suffix('.json').read_text())
    if action=='volume':
        requested=percent(sys.argv[2])
        # Eww scales emit onchange for model updates as well as user drags.
        # Equal values are refreshes, not user intent; never reset mixer state.
        if not state['has_audio'] or abs(requested-state['volume'])<.6:return
        call(['pactl','set-sink-volume','@DEFAULT_SINK@',str(requested)+'%']);send('show',kind='volume')
    elif action=='brightness':
        import brightness
        requested=percent(sys.argv[2])
        if not state['has_brightness'] or abs(requested-state['brightness'])<.6:return
        brightness.set_percent(state['brightness_id'],requested);send('show',kind='brightness')
    elif action=='media':
        import media_backend
        requested=sys.argv[2]
        if requested=='play-pause':requested='pause' if state['playing'] else 'play'
        media_backend.action(state['player'],requested);send('show',kind='media')
    else:raise ValueError('action')


if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
