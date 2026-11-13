#!/usr/bin/env python3
"""Check real Chrome maximize/restore and a fixed Eww reservation privately."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('XDG_STATE_HOME', ''))
if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run only through smoke.py --maximize-probe-only')
BASE = Path(os.environ['XDG_CONFIG_HOME']) / 'niri'
sys.path[:0] = [str(BASE / 'shell'), str(ROOT / 'tools')]
import session_probe
sys.path.insert(0, str(BASE / 'shell'))  # Keep theme writes in the private copy.

ARTIFACTS = ROOT / '.validation/wallpaper-unified-20261013/maximize'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASELINE = os.environ.get('SELANDIA_MAXIMIZE_BASELINE')
if BASELINE:
    for name in ('shell/bar_backend.py', 'shell/appearance.py', 'shell/eww_input.py', 'eww/input_region.rs', 'theme/theme.kdl'):
        shutil.copy2(Path(BASELINE) / 'niri' / name, BASE / name)
import appearance, island, bar_backend


def wait(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('Private maximize probe timed out')


def windows():
    return json.loads(session_probe.niri('--json', 'windows').stdout)


def browser_window():
    return next((window for window in windows() if window.get('title', '').startswith('Selandia maximize probe')), None)


def geometry():
    try:
        runtime = json.loads((Path(os.environ['XDG_RUNTIME_DIR']) / 'selandia-eww-runtime.json').read_text())
        return {kind: json.loads((Path(runtime['geometry']) / (kind + '.json')).read_text()) for kind in ('left', 'right', 'island')}
    except (OSError, ValueError, KeyError):
        return {}


def rectangle(window):
    layout = window['layout']
    tile = layout['tile_pos_in_workspace_view']
    offset = layout['window_offset_in_tile']
    if tile is not None:
        return [tile[0] + offset[0], tile[1] + offset[1], *layout['window_size']]
    # This Niri build omits positions from normal IPC snapshots. The fixture
    # fills the work area when maximized and is explicitly centred on restore.
    width,height=layout['window_size']
    if width==1600:
        return [0,1000-height,width,height]
    reserved=bar_backend.reserved_height(16) if not BASELINE else 67
    return [(1600-width)/2,reserved+(1000-reserved-height)/2,width,height]


def main():
    chrome = shutil.which('google-chrome-stable') or shutil.which('chromium')
    if not chrome:
        raise RuntimeError('A Chromium browser is required for this native regression')
    preview = BASE / 'preview.kdl'
    preview.write_text(preview.read_text().replace('scale 1.5', 'scale 1.0'))
    assert session_probe.resize_host_window(int(sys.argv[1]),1600,os.environ['SELANDIA_PROBE_HOST_SOCKET'],height=1000)
    output = session_probe.connected_output()[0]
    session_probe.niri('output', output, 'scale', '1').check_returncode()
    appearance.apply_settings({**appearance.load_settings(), 'font_size':16, 'wallpaper_colors':False})
    xml=ROOT/'tools/protocols/wlr-virtual-pointer.xml';h=PRIVATE/'wlr-virtual-pointer-client.h';c=PRIVATE/'pointer.c';pointer=PRIVATE/'pointer'
    for kind,target in [('client-header',h),('private-code',c)]:
        subprocess.run(['wayland-scanner',kind,str(xml),str(target)],check=True,timeout=5)
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client'],text=True,timeout=5).split()
    subprocess.run(['cc','-O2','-I',str(PRIVATE),str(ROOT/'tools/pointer_probe.c'),str(c),'-o',str(pointer),*flags],check=True,timeout=30)
    gtk3 = Path(os.environ['XDG_CONFIG_HOME']) / 'gtk-3.0'
    gtk3.mkdir(parents=True, exist_ok=True)
    (gtk3 / 'settings.ini').write_text('[Settings]\ngtk-decoration-layout=icon:minimize,maximize,close\n')
    page = PRIVATE/'maximize.html'
    page.write_text('<!doctype html><title>Selandia maximize probe</title><body style="background:#d9e6f0;font:32px sans-serif;padding:40px">Selandia maximize probe<br>Private profile · local page</body>')
    children, logs, records = [], [], {}

    def start(name, argv, env=None):
        log=(ARTIFACTS/(name+'.log')).open('w');logs.append(log)
        process=subprocess.Popen(argv,env=env,stdout=log,stderr=subprocess.STDOUT);children.append(process)
        return process

    def capture(name):
        records[name] = {'window': browser_window(), 'bar': geometry()}
        (ARTIFACTS/('baseline-records.json' if BASELINE else 'records.json')).write_text(json.dumps(records,indent=2)+'\n')
        session_probe.screenshot(ARTIFACTS/(name+'.png'))
        island.send('dismiss');time.sleep(.5)

    try:
        start('bar', [sys.executable,'-B',str(BASE/'shell/bar_backend.py')])
        wait(lambda:geometry().get('island'))
        chrome_env = dict(os.environ, GSETTINGS_BACKEND='keyfile')
        subprocess.run(['gsettings', 'set', 'org.gnome.desktop.wm.preferences', 'button-layout', ':minimize,maximize,close'], env=chrome_env, check=True, timeout=5)
        start('chrome', [chrome,'--user-data-dir='+str(PRIVATE/'chrome-profile'),'--ozone-platform=wayland',
                        '--no-first-run','--no-default-browser-check','--disable-background-networking',
                        '--disable-component-update','--disable-default-apps','--disable-sync','--password-store=basic',
                        '--start-maximized',page.as_uri()], env=chrome_env)
        wait(browser_window);time.sleep(1)
        capture('baseline' if BASELINE else 'maximized')
        window=browser_window();bounds=rectangle(window)
        (ARTIFACTS/('baseline-records.json' if BASELINE else 'records.json')).write_text(json.dumps(records,indent=2)+'\n')
        if BASELINE:
            assert bounds[1]<12+geometry()['right']['height'],bounds
            print('REPRODUCED: Chrome client maximize overlaps the non-exclusive bar',flush=True)
            return
        reserved=bar_backend.reserved_height(16)
        assert abs(bounds[1]-reserved)<=1,(bounds,reserved)
        assert bounds[1]>=12+geometry()['right']['height'],bounds
        assert geometry()['island']['exclusive_zone']==reserved-12
        assert all(geometry()[kind]['exclusive_zone']==-1 for kind in ('left','right'))
        island.send('show',kind='volume');wait(lambda:geometry()['island']['height']>70);time.sleep(.3)
        assert rectangle(browser_window())==bounds,(bounds,rectangle(browser_window()))
        capture('expanded')
        island.send('dismiss');wait(lambda:geometry()['island']['height']<70)
        # Click Chrome's own restore button in its header, then maximize it again.
        subprocess.run([str(pointer),str(round(bounds[0]+bounds[2]-52)),str(round(bounds[1]+20)),'1600','1000','click'],check=True,timeout=5)
        wait(lambda:rectangle(browser_window())!=bounds)
        session_probe.niri('action','center-window','--id',str(window['id'])).check_returncode()
        time.sleep(.4)
        restored=rectangle(browser_window());capture('restored')
        subprocess.run([str(pointer),str(round(restored[0]+restored[2]-52)),str(round(restored[1]+20)),'1600','1000','click'],check=True,timeout=5)
        wait(lambda:rectangle(browser_window())==bounds)
        capture('button-maximized')
        session_probe.niri('action','fullscreen-window','--id',str(window['id'])).check_returncode()
        wait(lambda:browser_window()['layout']['window_size']==[1600,1000]);time.sleep(.5)
        full=rectangle(browser_window());assert full==[0,0,1600,1000],full
        capture('fullscreen')
        session_probe.niri('action','fullscreen-window','--id',str(window['id'])).check_returncode()
        wait(lambda:browser_window()['layout']['window_size']!=[1600,1000]);time.sleep(.5)
        records['passed']={'reserved':reserved,'client_maximize':True,'header_button_restore_and_maximize':True,'expansion_keeps_window_fixed':True,'fullscreen_fills_output':True}
        (ARTIFACTS/'records.json').write_text(json.dumps(records,indent=2)+'\n')
        print('PASS real Chrome client maximize, header restore/maximize clicks, fixed expanded reservation and fullscreen',flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=8)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        for log in logs:log.close()


if __name__=='__main__':main()
