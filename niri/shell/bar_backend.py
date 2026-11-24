#!/usr/bin/env python3
"""Three bounded Eww layers, supervised by the existing managed bar service."""
from functools import lru_cache
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import hashlib
from appearance import BASE, load_settings, mascot_asset
import component_preferences
import i18n
from i18n import tr
import eww_input


@lru_cache(maxsize=32)
def _measure_capsule_height(_font_family, size):
    # Pure-math line height avoids loading GTK/Pango/Cairo into the resident
    # Python supervisor (~45 MiB RSS saved) while matching GTK font metrics.
    return max(44, round(size * 1.35) + 22)


def capsule_height(size):
    return _measure_capsule_height(load_settings()['font'], size)


def reserved_height(size):
    return max(round(size*2.8+22),capsule_height(size)+12)


def geometry(width, size=12):
    width=max(320,int(width));factor=max(1,size/12)
    compact=width<1500 or (size>=15 and width<2400)
    left=min(round(250*factor),round(width*.27))
    right=min(round(620*factor),round(width*(.35 if compact else .38)))
    maximum=max(160,min(round(460*factor),int(2*min(width/2-left-12,width/2-right-12)-24)))
    # Keep a real gap on both sides even when the output is very narrow.
    right=min(right,max(96,int(width/2-12-maximum/2)))
    # Added software gets its own bounded space; existing capsule widths and island limit stay unchanged.
    left=min(left+round(250*factor),max(left,int(width/2-maximum/2-24)))
    target_collapsed=round((144 if compact else 214)*factor)
    collapsed=min(target_collapsed,max(96,maximum-36)) if maximum>132 else min(target_collapsed,maximum)
    return {'left':left,'right':right,'island':maximum,'collapsed':collapsed,
            'height':capsule_height(size),'compact':compact}


def outputs():
    from niri_events import request
    values=request('Outputs')
    connected=[(key,item) for key,item in values.items() if item.get('logical')]
    # Single-monitor setups (the common case) skip importing GTK/GDK altogether,
    # keeping the resident bar supervisor lean (~18 MiB instead of ~64 MiB).
    if len(connected) > 1:
        try:
            import gi
            gi.require_version('Gdk','3.0')
            from gi.repository import Gdk,GLib
            context=GLib.MainContext.default()
            for _ in range(20):
                if not context.pending():break
                context.iteration(False)
            display=Gdk.Display.get_default();ordered=[]
            for index in range(display.get_n_monitors()):
                rectangle=display.get_monitor(index).get_geometry()
                match=next((entry for entry in connected if all(entry[1]['logical'][field]==getattr(rectangle,field) for field in ('x','y','width','height'))),None)
                if match:ordered.append(match)
            if len(ordered)==len(connected):connected=ordered
        except (ImportError,AttributeError,ValueError):pass
    return [(key,item['logical']['width']) for key,item in connected]


def render(monitors, *, size=12):
    q=lambda value:json.dumps(value,ensure_ascii=False)
    def node(name,attrs=None,*children):
        properties=' '.join(':'+key+' '+value for key,value in (attrs or {}).items())
        return '('+name+(' '+properties if properties else '')+(' '+' '.join(children) if children else '')+')'
    def label(value,**attrs):return node('label',{'text':value,**attrs})
    def box(*children,**attrs):return node('box',{'space-evenly':'false',**attrs},*children)
    # GUI actions outlive the click handler. Niri owns and reaps the spawned
    # application; Eww's bounded command timeout cannot kill its foreground UI.
    desktop='niri msg action spawn -- '+shlex.quote(str(BASE/'scripts/desktop'))
    bridge='python3 -B '+shlex.quote(str(BASE/'shell/island.py'))
    def button(text,command,tooltip=None,enabled='true',css='pill'):
        return node('button',{'class':q(css),'onclick':q(command),'timeout':q('5s'),'tooltip':q(tooltip or text),'active':enabled},label(q(text)))
    initial={'kind':'idle','width':96,'open':False,'title':'','summary':'','cover':'',
             'can_next':False,'can_previous':False,'can_toggle':False,'media':False,'playing':False,'player':'','progress':0,'has_progress':False,
             'volume':0,'has_audio':False,'muted':False,'brightness':0,'has_brightness':False,
             'clock':'','clock_short':'','clock_time':'','clock_date':'','app_name':tr('Desktop','桌面'),'window_title':tr('No focused window','没有当前窗口'),'app_id':'','window_id':None,'workspaces':{key:[] for key,_ in monitors},'network':'','battery':'',
             'cpu_text':'—','memory_text':'—','network_text':'—','temperature_text':'—','gpu_text':'—','metrics_detail':'','metrics_available':False,
             'notification_icon':'dialog-information-symbolic','reduced':load_settings()['reduced_motion'],'tray':False}
    lines=['(deflisten state :initial '+q(json.dumps(initial))+' '+q(bridge+' listen')+')'];names=[]
    for index,(monitor,width) in enumerate(monitors):
        g=geometry(width,size);narrow=g['compact'];very_narrow=width<900;key=q(monitor)
        def window(name,content,anchor,width,namespace):
            names.append(name)
            geometry=node('geometry',{'anchor':q(anchor),'x':q('0px' if anchor=='top center' else '12px'),'y':q('12px'),'width':q(str(width)+'px'),'height':q(str(g['height'])+'px')})
            return node('defwindow '+name,{'monitor':str(index),'namespace':q(namespace),'stacking':q('fg'),'focusable':'false','exclusive':'false','resizable':'true','geometry':geometry},content)
        workspace='(for item in {state.workspaces['+key+']} '+node('button',{'class':'{item.active ? "workspace active" : "workspace"}','onclick':q(bridge+' workspace ${item.id}'),'timeout':q('5s'),'tooltip':'{item.name}'},label('{item.name}',**{'limit-width':'2' if narrow else '3'}))+')'
        segment=q('segment compact' if narrow else 'segment')
        is_zh=i18n.get_language().startswith('zh')
        app_limit = '5' if (narrow and is_zh) else '8' if narrow else '16' if is_zh else '20'
        application=node('button',{'class':q('pill current-app'),'hexpand':'false','onclick':q('niri msg action toggle-overview'),'timeout':q('5s'),'tooltip':'{state.window_title}'},
                         box(label(q('●'),**{'class':q('app-dot')}),
                             label('{state.app_name}',**{'class':q('app-label'),'truncate':'true','limit-width':q(app_limit),'xalign':'0'}),
                             spacing='2'))
        avatar_size=str(max(22,min(32,g['height']-16)))
        avatar_path=str(mascot_asset(None,'avatar64'))
        launcher=node('button',{'class':q('pill launcher-btn'),'onclick':q(desktop+' launcher'),'timeout':q('5s'),'tooltip':q(tr('Applications','应用'))},
                      node('image',{'class':q('launcher-avatar'),'path':q(avatar_path),'image-width':avatar_size,'image-height':avatar_size}))
        left=box(launcher,node('box',{'class':q('separator')}),
                 box(workspace,spacing='3' if narrow else '6'),node('box',{'class':q('separator')}),
                 application,**{'class':segment,'spacing':'4' if narrow else '6','halign':q('start'),'hexpand':'false'})
        host_class='{state.reduced ? "bar-host reduce-motion" : "bar-host"}'
        left_outer=box(left,halign=q('start'),hexpand='true',**{'class':host_class})
        lines.append(window('selandia-left-'+str(index),left_outer,'top left',g['left'],'selandia-bar-left'))
        def resource(icon,value,label_text,kind):
            return node('box',{'class':q('resource '+kind),'tooltip':q(label_text)},
                        label(q(icon),**{'class':q('resource-icon')}),
                        label(value,**{'class':q('resource-value')}))
        telemetry_items = [resource('󰻠 CPU','{state.cpu_text}',tr('Processor','处理器'),'cpu')]
        if not very_narrow:
            telemetry_items.append(resource('󰍛 RAM','{state.memory_text}',tr('Memory','内存'),'ram'))
        if not narrow:
            telemetry_items.append(resource('󰔏 TEMP','{state.temperature_text}',tr('Temperature','温度'),'temp'))
        telemetry=node('button',{'class':q('pill resources bar-right'),'onclick':q(desktop+' system'),'timeout':q('5s'),'tooltip':q('{state.metrics_detail}')},
            box(*telemetry_items,**{'class':q('resource-row'),'spacing':'6' if narrow else '8'}))
        tray=(button('⋯',bridge+' tray',tr('System tray','系统托盘')) if narrow else box(node('systray',{'icon-size':'16','spacing':'4'}),**{'class':q('pill'),'tooltip':q(tr('System tray','系统托盘'))}))
        if very_narrow:tray=node('box',{'visible':'false'})
        battery=label('{state.battery}',**{'class':q('pill battery'),'tooltip':q(tr('Battery','电池')),'visible':'false' if narrow else '{state.battery != ""}'})
        audio=node('button',{'class':'{state.muted ? "pill audio-btn muted" : "pill audio-btn"}','onclick':q(bridge+' show volume'),'timeout':q('5s'),'visible':'false' if very_narrow else 'true',
                            'tooltip':'{state.muted ? '+q(tr('Muted','已静音'))+' : '+q(tr('Volume','音量'))+'}'},
                   box(label('{state.muted ? "󰝟" : "󰕾"}'),
                       label(q('${state.volume}%'),**{'visible':'false' if narrow else '{state.has_audio}'}),
                       spacing='3'))
        network_button=node('button',{'class':q('pill network-btn'),'onclick':q(desktop+' network'),'timeout':q('5s'),'tooltip':q(tr('Network','网络'))},
                            box(label(q('󰖩 NET'),**{'class':q('resource-icon')}),
                                *( [] if narrow else [label('{state.network_text}',**{'class':q('resource-value'),'visible':'{state.network_text != "—"}'})] ),
                                spacing='3'))
        hardware=box(*([] if narrow else [network_button]),audio,battery,tray,spacing='2' if narrow else '4')
        actions=box(*([] if very_narrow else [button('󰂚',desktop+' notification-toggle',tr('Notifications','通知'))]),
                    button('󰒓',desktop+' control',tr('Control Center','控制中心'),css='pill control-btn bar-right'),
                    spacing='2' if narrow else '4')
        sep=node('box',{'class':q('separator')})
        right=box(telemetry,sep,hardware,sep,actions,**{'class':segment,'halign':q('end'),'hexpand':'false','spacing':'2' if narrow else '4'})
        right_outer=box(right,halign=q('end'),hexpand='true',**{'class':host_class})
        lines.append(window('selandia-right-'+str(index),right_outer,'top right',g['right'],'selandia-bar-right'))
        idle_media=node('button',{'class':q('island-media-btn'),'onclick':q(bridge+' show media'),'timeout':q('5s'),'tooltip':q(tr('Media','媒体'))},
                        label('{state.playing ? "󰎈" : "✦"}',**{'class':q('island-idle-icon')}))
        idle_clock=node('button',{'class':q('island-clock'),'onclick':q(desktop+' calendar'),'timeout':q('5s'),'tooltip':q(tr('Open calendar','打开日历'))},
                        box(label('{state.clock_time}',**{'class':q('clock-time')}),
                            *( [] if narrow else [label('{state.clock_date}',**{'class':q('clock-date')})] ),
                            spacing='6',valign=q('center')))
        idle=box(idle_media,idle_clock,**{'class':q('island-idle-row'),'halign':q('center'),'valign':q('center'),'spacing':'6'})
        cover=box(node('stack',{'same-size':'false','selected':'{state.cover != "" ? 0 : 1}'},
            node('image',{'path':'{state.cover != "" ? state.cover : '+q(str(BASE/'assets/icons/empty.svg'))+'}','image-width':'36','image-height':'36'}),
            node('image',{'icon':q('audio-x-generic-symbolic'),'icon-size':q('dialog')})),**{'class':q('island-cover')})
        progress=node('stack',{'same-size':'false','selected':'{state.has_progress ? 0 : 1}'},node('progress',{'value':'{state.progress}'}),label(q(tr('Duration unavailable','时长不可用')),**{'class':q('island-summary')}))
        controls=box(button('⏮',bridge+' media previous',tr('Previous track','上一曲'),enabled='{state.can_previous}'),
                     button('⏯',bridge+' media play-pause',tr('Play or pause','播放或暂停'),enabled='{state.can_toggle}',css='pill island-play'),
                     button('⏭',bridge+' media next',tr('Next track','下一曲'),enabled='{state.can_next}'),**{'halign':q('center'),'spacing':'10'})
        title=label('{state.media ? state.title : '+q(tr('No media playing','暂无播放'))+'}',**{'class':q('island-title'),'limit-width':'8' if narrow else '32','xalign':'0'})
        media=box(box(cover,title,orientation=q('v' if narrow else 'h'),spacing='10'),progress,controls,orientation=q('v'),spacing='6')
        slider=node('scale',{'orientation':q('h'),'min':'0','max':'100','draw-value':'false','value':'{state.kind == "brightness" ? state.brightness : state.volume}','onchange':q(bridge+' ${state.kind} {}'),'timeout':q('5s'),'active':'{state.kind == "brightness" ? state.has_brightness : state.has_audio}'})
        volume=box(label('{state.title}',**{'class':q('island-title'),'limit-width':'8' if narrow else '32','wrap':'true'}),slider,orientation=q('v'),spacing='6')
        notify_head=box(node('image',{'icon':'{state.notification_icon}','icon-size':q('large-toolbar')}),
                        label('{state.title}',**{'class':q('island-title'),'limit-width':'8' if narrow else '34','wrap':'true','hexpand':'true','xalign':'0'}),
                        button('×',bridge+' dismiss',tr('Dismiss preview','忽略')),spacing='8')
        notification=box(notify_head,label('{state.summary}',**{'class':q('island-summary'),'limit-width':'8' if narrow else '52','wrap':'true','xalign':'0'}),orientation=q('v'),spacing='6')
        stack=node('stack',{'same-size':'false','selected':'{state.kind == "idle" ? 0 : state.kind == "media" ? 1 : state.kind == "notification" ? 3 : state.kind == "tray" ? 4 : 2}','transition':'{state.reduced ? "none" : "crossfade"}'},idle,media,volume,notification,box(node('systray',{'icon-size':'16','spacing':'4'})))
        animated='{round('+str(g['collapsed'])+' + (state.width - 96) * '+str(g['island']-g['collapsed'])+' / 364, 0)}'
        # Eww's width/height property setter preserves allocated_height when
        # height is omitted: dynamic width would freeze an expanded page's
        # height. -1 keeps GTK's natural content height for every animation frame.
        island_class='{state.reduced ? (state.open ? (state.playing ? "island expanded playing reduce-motion" : "island expanded reduce-motion") : (state.playing ? "island playing reduce-motion" : "island reduce-motion")) : (state.open ? (state.playing ? "island expanded playing" : "island expanded") : (state.playing ? "island playing" : "island"))}'
        content=box(stack,**{'class':island_class,'orientation':q('v'),'valign':q('start'),'width':animated,'height':'-1'})
        lines.append(window('selandia-island-'+str(index),content,'top center',g['collapsed'],'selandia-island'))
    return '\n'.join(lines)+'\n',names


def unavailable(reason):
    component_preferences.health('eww-failed', reason)
    message=tr('Eww failed; systemd will restart it. Install missing dependencies: ',
               'Eww 失败，systemd 将自动重启。缺少依赖时安装：') + 'paru -S --needed eww anyrun'
    print(message+'\n'+str(reason),file=sys.stderr,flush=True)
    try:subprocess.run(['notify-send','-a','Selandia Niri',message],timeout=3,check=False)
    except (OSError,subprocess.SubprocessError):pass
    raise RuntimeError(str(reason))


def client(directory, *arguments, timeout=3):
    # Eww 0.6's IPC reply expires after 100ms. An ordinary `open` client
    # interprets that as a missing server and forks another daemon. Never let
    # clients start daemons: this supervisor exclusively owns and reaps one.
    return subprocess.run(['eww','--no-daemonize','-c',str(directory),*arguments],
                          capture_output=True,text=True,timeout=timeout)


def open_windows(directory, names, child):
    client(directory,'open-many',*names)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if child.poll() is not None:raise RuntimeError('Eww daemon exited while opening windows')
        active=client(directory,'active-windows')
        actual={line.partition(':')[0].strip() for line in active.stdout.splitlines()}
        if active.returncode==0 and actual==set(names):
            # All three native widgets must have been allocated as well.
            try:
                values=[json.loads((directory/'geometry'/(kind+'.json')).read_text()) for kind in ('left','right','island')]
                if all(value['width']>0 and value['capsules'] for value in values):return
            except (OSError,ValueError,KeyError):pass
        time.sleep(.1)
    raise RuntimeError('Eww windows did not become ready')


def bridge_alive():
    import island
    try:
        state=json.loads(island.endpoint().with_suffix('.json').read_text())
        pid=state['bridge_pid'];heartbeat=state['heartbeat']
        if not isinstance(pid,int) or pid<=0 or not isinstance(heartbeat,int):return False
        os.kill(pid,0)
        return 0<=time.monotonic()-heartbeat<10
    except (OSError,ValueError,KeyError):return False


def eww_environment(helper,directory):
    environment=eww_input.clean_environment()
    # Eww creates two async runtimes; cap their idle workers independently of
    # GTK/rendering and Tokio's on-demand blocking pool. Honour user overrides.
    environment.setdefault('TOKIO_WORKER_THREADS','2')
    environment.update(SELANDIA_EWW_INPUT_LIB=str(helper),SELANDIA_EWW_GEOMETRY=str(directory/'geometry'),
                       SELANDIA_EWW_EXCLUSIVE_ZONE=str(reserved_height(load_settings()['font_size'])-12),
                       LD_PRELOAD=str(helper)+(':'+environment['LD_PRELOAD'] if environment.get('LD_PRELOAD') else ''))
    return environment


def run():
    component_preferences.effective('bar')
    child=None;stopping=[False];failure=None
    stopped=threading.Event()
    def stop(*_):
        stopping[0]=True
        stopped.set()
        if child and child.poll() is None:child.terminate()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    with tempfile.TemporaryDirectory(prefix='selandia-eww-',dir=runtime) as temporary:
        directory=Path(temporary)
        try:
            helper=eww_input.library()
            environment=eww_environment(helper,directory)
            if os.environ.get('SELANDIA_PRIVATE_PROBE')=='1' and os.environ.get('SELANDIA_EWW_TRACE')=='1':environment['WAYLAND_DEBUG']='1'
            appearance_path=directory/'runtime.json'
            appearance_path.write_text(json.dumps({'config':str(directory),'geometry':str(directory/'geometry')}))
            runtime_info=runtime/'selandia-eww-runtime.json'
            os.replace(appearance_path,runtime_info)
            os.chmod(runtime_info,0o600)
            import appearance
            settings=load_settings()
            appearance.apply_settings(settings,bar='eww')
            previous=outputs()
            text,names=render(previous,size=settings['font_size'])
            (directory/'eww.yuck').write_text(text)
            (directory/'eww.css').write_text('@import '+json.dumps(str(BASE/'theme/eww.css'))+';\n')
            child=subprocess.Popen(['eww','--force-wayland','--no-daemonize','-c',str(directory),'daemon'],env=environment)
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                if child.poll() is not None:raise RuntimeError('Eww daemon exited')
                ping=client(directory,'ping',timeout=2)
                if ping.returncode==0:break
                time.sleep(.1)
            else:raise RuntimeError('Eww daemon not ready')
            open_windows(directory,names,child)
            deadline=time.monotonic()+10
            while not bridge_alive() and time.monotonic()<deadline:time.sleep(.1)
            if not bridge_alive():raise RuntimeError('Island event bridge did not become ready')
            appearance_path.write_text(json.dumps({'config':str(directory),'geometry':str(directory/'geometry'),
                                                  'ready':True,'daemon_pid':child.pid,'supervisor_pid':os.getpid()}))
            os.chmod(appearance_path,0o600);os.replace(appearance_path,runtime_info)
            component_preferences.health('eww-ready')
            expected=hashlib.sha256((directory/'eww.yuck').read_bytes()).digest()
            last_check=time.monotonic()
            while not stopping[0] and child.poll() is None:
                if stopped.wait(1):
                    break
                if time.monotonic()-last_check>=3:
                    last_check=time.monotonic()
                    if hashlib.sha256((directory/'eww.yuck').read_bytes()).digest()!=expected:raise RuntimeError('Eww runtime configuration changed unexpectedly')
                    if not bridge_alive():raise RuntimeError('Island event bridge stopped')
                    current=outputs()
                    if current!=previous:
                        text,names=render(current,size=load_settings()['font_size'])
                        (directory/'eww.yuck').write_text(text)
                        expected=hashlib.sha256(text.encode()).digest()
                        client(directory,'close-all')
                        client(directory,'reload')
                        open_windows(directory,names,child)
                        previous=current
            if not stopping[0]:raise RuntimeError('Eww daemon stopped unexpectedly')
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
            if child and child.poll() is None:child.terminate()
            if child:
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
            if not stopping[0]:failure=str(error)
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
            (runtime/'selandia-eww-runtime.json').unlink(missing_ok=True)
    if failure and not stopping[0]:unavailable(failure)


if __name__=='__main__':run()
