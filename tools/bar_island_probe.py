#!/usr/bin/env python3
"""Real Eww allocations, pixels and pointer events, private compositor only."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PRIVATE=Path(os.environ.get('XDG_STATE_HOME',''))
if os.environ.get('SELANDIA_PRIVATE_PROBE')!='1' or not PRIVATE.name.startswith('selandia-smoke-'):raise SystemExit('Use smoke.py --bar-island-probe-only')
BASE=Path(os.environ['XDG_CONFIG_HOME'])/'niri';sys.path[:0]=[str(BASE/'shell'),str(ROOT/'tools')]
import appearance,session_probe,island,bar_backend
# No PulseAudio fallback connection to the real session, even with a private bus.
os.environ['PULSE_SERVER']='unix:'+str(PRIVATE/'no-host-audio')
EVID=ROOT/'.validation/bar-capsules-20261011/bar-island';EVID.mkdir(parents=True,exist_ok=True)
def wait(test,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if test():return
        time.sleep(.05)
    raise AssertionError('native Eww condition timed out')
def canvas():
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('GtkLayerShell','0.1')
    from gi.repository import Gtk,Gdk,GtkLayerShell as L
    w=Gtk.Window();L.init_for_window(w);L.set_namespace(w,'selandia-probe-canvas');L.set_layer(w,L.Layer.BOTTOM)
    # The wallpaper fixture fills the monitor even when the bar reserves space.
    L.set_exclusive_zone(w,-1)
    for e in (L.Edge.TOP,L.Edge.BOTTOM,L.Edge.LEFT,L.Edge.RIGHT):L.set_anchor(w,e,True)
    area=Gtk.DrawingArea();area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK);clicks=[]
    (PRIVATE/'clicks.json').write_text('[]')
    def click(_w,e):clicks.append([e.x,e.y]);(PRIVATE/'clicks.json').write_text(json.dumps(clicks));return True
    def draw(w,c):
        c.set_source_rgb(.85,.66,.24);c.paint()
        for y in range(0,w.get_allocated_height(),20):
            for x in range(0,w.get_allocated_width(),20):
                if (x//20+y//20)%2:c.set_source_rgb(.30,.47,.64);c.rectangle(x,y,20,20);c.fill()
        c.set_source_rgb(.95,.93,.72)
        for x in range(3,w.get_allocated_width(),17):c.rectangle(x,0,1,w.get_allocated_height())
        c.fill();(PRIVATE/'canvas-ready').write_text('ready');return True
    area.connect('button-press-event',click);area.connect('draw',draw);w.add(area);w.show_all();Gtk.main()
def application():
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk,Gio,GLib,Gdk
    GLib.set_prgname(sys.argv[2]);Gdk.set_program_class(sys.argv[2])
    app=Gtk.Application(application_id=sys.argv[2],flags=Gio.ApplicationFlags.NON_UNIQUE)
    def activate(app):
        window=Gtk.ApplicationWindow(application=app,title=sys.argv[3]);window.set_default_size(260,140)
        window.add(Gtk.Label(label=sys.argv[3]));window.show_all()
    app.connect('activate',activate);app.run([])

def notifications():
    from gi.repository import Gio,GLib
    xml='''<node><interface name="org.freedesktop.Notifications"><method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method><method name="GetCapabilities"><arg type="as" direction="out"/></method><method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method></interface></node>'''
    con=Gio.bus_get_sync(Gio.BusType.SESSION,None);node=Gio.DBusNodeInfo.new_for_xml(xml)
    def method(c,s,p,i,m,args,invocation):
        if m=='Notify':value=GLib.Variant('(u)',(1,))
        elif m=='GetCapabilities':value=GLib.Variant('(as)',(['body'],))
        else:value=GLib.Variant('(ssss)',('Probe','Selandia','1','1.2'))
        invocation.return_value(value)
    con.register_object('/org/freedesktop/Notifications',node.interfaces[0],method,None,None)
    con.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.Notifications',4)),None,Gio.DBusCallFlags.NONE,2000,None)
    # This geometry fixture accepts previews; policy transitions are exercised
    # separately against the real private SwayNC in notification_probe.py.
    policy_xml='<node><interface name="org.erikreider.swaync.cc"><method name="GetSubscribeData"><arg type="(bbub)" direction="out"/></method></interface></node>'
    def policy_method(c,s,p,i,m,args,invocation):
        invocation.return_value(GLib.Variant('((bbub))',((False,False,0,False),)))
    policy_node=Gio.DBusNodeInfo.new_for_xml(policy_xml)
    con.register_object('/org/erikreider/swaync/cc',policy_node.interfaces[0],policy_method,None,None)
    con.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.erikreider.swaync.cc',4)),None,Gio.DBusCallFlags.NONE,2000,None)
    GLib.MainLoop().run()
def main():
    import gi
    gi.require_version('GdkPixbuf','2.0');from gi.repository import GdkPixbuf
    # Render actual mute feedback without connecting to or changing host audio.
    audio_bin=PRIVATE/'audio-bin';audio_bin.mkdir()
    audio=audio_bin/'pactl'
    audio.write_text('#!'+sys.executable+'\n'+'''import signal,sys
if sys.argv[1:]==['subscribe']:
    while True:signal.pause()
elif sys.argv[1:]==['get-sink-volume','@DEFAULT_SINK@']:print('Volume: 50%')
elif sys.argv[1:]==['get-sink-mute','@DEFAULT_SINK@']:print('Mute: yes')
else:raise SystemExit('Unexpected audio command in read-only fixture')
''')
    audio.chmod(0o700);os.environ['PATH']=str(audio_bin)+os.pathsep+os.environ['PATH']
    # Persist the test scale in this private copied config: a generated theme
    # reload must not reassert preview.kdl's normal 1.5x scale mid-measurement.
    preview=BASE/'preview.kdl';preview.write_text(preview.read_text().replace('scale 1.5','scale 1.0'))
    xml=ROOT/'tools/protocols/wlr-virtual-pointer.xml';h=PRIVATE/'wlr-virtual-pointer-client.h';c=PRIVATE/'pointer.c';pointer=PRIVATE/'pointer'
    for kind,target in [('client-header',h),('private-code',c)]:subprocess.run(['wayland-scanner',kind,str(xml),str(target)],check=True, timeout=5)
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client'],text=True, timeout=5).split()
    subprocess.run(['cc','-O2','-I',str(PRIVATE),str(ROOT/'tools/pointer_probe.c'),str(c),'-o',str(pointer),*flags],check=True, timeout=30)
    def geom():
        try:
            data=json.loads((Path(os.environ['XDG_RUNTIME_DIR'])/'selandia-eww-runtime.json').read_text())
            if not data.get('ready'):return None
            root=Path(data['geometry'])
            return {k:json.loads((root/(k+'.json')).read_text()) for k in ('left','right','island')}
        except (OSError,ValueError):return None
    def state():
        try:return json.loads(island.endpoint().with_suffix('.json').read_text())
        except (OSError,ValueError):return {}
    def shot(name):
        p=EVID/(name+'.png');session_probe.screenshot(p)
        image=GdkPixbuf.Pixbuf.new_from_file(str(p))
        # Niri emits a real screenshot-saved Notify, which correctly opens the
        # island. Dismiss that test event before the next geometry/click check.
        if island.endpoint().is_socket():
            wait(lambda:state().get('kind')=='notification',seconds=4)
            island.send('dismiss');wait(lambda:state().get('kind')=='idle')
            time.sleep(.7)
        return image
    def pixel(im,x,y):
        at=int(y)*im.get_rowstride()+int(x)*im.get_n_channels();return tuple(im.get_pixels()[at:at+3])
    def click(x,y,width):
        count=lambda:len(json.loads((PRIVATE/'clicks.json').read_text())) if (PRIVATE/'clicks.json').exists() else 0
        before=count();subprocess.run([str(pointer),str(int(x)),str(int(y)),str(width),'1000','click'],check=True, timeout=5);time.sleep(.12)
        print(json.dumps({'click':[x,y],'delivered':count()-before,'kind':state().get('kind'),'native':geom()}),flush=True)
        return count()-before
    children=[];logs=[];results=[];images={}
    def start(name,cmd):
        log=(EVID/(name+'.log')).open('w');logs.append(log);p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT);children.append(p);return p
    def stop(p):
        p.terminate()
        try:p.wait(timeout=8)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
    try:
        start('notifications',[sys.executable,'-B',__file__,'--notifications'])
        subprocess.run(['gdbus','wait','--session','--timeout','10','org.freedesktop.Notifications'],check=True,timeout=12)
        subprocess.run(['gdbus','wait','--session','--timeout','10','org.erikreider.swaync.cc'],check=True,timeout=12)
        for width in (1600,800):
            assert session_probe.resize_host_window(int(sys.argv[1]),width,os.environ['SELANDIA_PROBE_HOST_SOCKET'],height=1000)
            out=session_probe.connected_output()[0];session_probe.niri('output',out,'scale','1').check_returncode()
            wait(lambda:session_probe.connected_output()[1]==width)
            (PRIVATE/'canvas-ready').unlink(missing_ok=True)
            bg=start('canvas-'+str(width),[sys.executable,'-B',__file__,'--canvas']);wait(lambda:(PRIVATE/'canvas-ready').exists());time.sleep(.3);baseline=shot(str(width)+'-baseline');time.sleep(.3)
            assert baseline.get_width()==width
            for size in (12,16,20):
                for alpha in (.2,1):
                    appearance.apply_settings({**appearance.load_settings(),'opacity':alpha,'font_size':size,'wallpaper_colors':False,'reduced_motion':False})
                    p=start(f'bar-{width}-{size}-{alpha}',[sys.executable,'-B',str(BASE/'shell/bar_backend.py')]);wait(lambda:geom() and state().get('clock') and state().get('desktop_available'));time.sleep(.3)
                    if width==1600 and size==12 and alpha==.2:
                        # Reordering separates stable IDs from displayed indexes.
                        workspace=next(item for item in json.loads(session_probe.niri('--json','workspaces').stdout) if item['is_focused'])
                        session_probe.niri('action','move-workspace-to-index','3').check_returncode()
                        session_probe.niri('action','focus-workspace','1').check_returncode()
                        subprocess.run([sys.executable,'-B',str(BASE/'shell/island.py'),'workspace',str(workspace['id'])],check=True,timeout=5)
                        current=next(item for item in json.loads(session_probe.niri('--json','workspaces').stdout) if item['is_focused'])
                        assert current['id']==workspace['id'] and current['idx']==3, current
                        session_probe.niri('action','move-workspace-to-index',str(workspace['idx'])).check_returncode()
                        (EVID/'workspace-id.json').write_text(json.dumps({'stable_id':workspace['id'],'moved_index':3,'passed':True}))
                        time.sleep(.3)
                    g=geom();idle=shot(f'{width}-{size}-{alpha}-idle');small=g['island']['width'];error=abs((width-small)//2+small/2-width/2)
                    (EVID/f'{width}-{size}-{alpha}-allocations.json').write_text(json.dumps(g,indent=2))
                    # Center comes from native screenshot pixels, not inferred anchors.
                    span=small//2+8
                    changed=[x for x in range(width//2-span,width//2+span) if any(max(abs(a-b) for a,b in zip(pixel(idle,x,y),pixel(baseline,x,y)))>3 for y in range(20,44))]
                    assert changed
                    error=abs((min(changed)+max(changed)+1)/2-width/2)
                    assert error<=4 and abs(max(changed)-min(changed)+1-small)<=8
                    heights={kind:[r['height'] for r in g[kind]['capsules']] for kind in ('left','right')}
                    island_height=g['island']['capsules'][0]['height']
                    # Side capsules are intentionally inset a few pixels inside the 44 px segment.
                    assert all(abs(h - island_height) <= 12 for rows in heights.values() for h in rows),(size,g)
                    assert 12+g['left']['width'] < (width-g['island']['width'])//2,g
                    clock_x=width-12-g['right']['width']+g['right']['capsules'][0]['x'];assert clock_x>width/2,g
                    gap=round((12+g['left']['width']+(width-small)/2)/2)
                    assert click(gap,24,width)==1,('gap input',g)
                    assert click((width-small)//2+1,13,width)==1,('corner input',g)
                    assert click(width//2,32,width)==0,('capsule input',g)
                    island.send('dismiss');wait(lambda:state().get('kind')=='idle');wait(lambda:geom()['island']['width']==small);time.sleep(.3)
                    island.send('show',kind='volume');sizes=[]
                    for _ in range(14):time.sleep(.04);sizes.append(geom()['island']['width'])
                    wait(lambda:geom()['island']['width']==bar_backend.geometry(width,size)['island'])
                    expanded=geom()
                    assert state()['muted'] and ('Muted' in state()['title'] or '已静音' in state()['title']),state()
                    shot(f'{width}-{size}-{alpha}-volume')
                    assert expanded['island']['width']>small,(small,sizes)
                    if g['left']!=expanded['left'] or g['right']!=expanded['right']:
                        (EVID/'layout-mismatch.json').write_text(json.dumps({'before':g,'after':expanded},indent=2))
                    assert (g['left']['width'],g['right']['width'])==(expanded['left']['width'],expanded['right']['width'])
                    assert any(small<n<expanded['island']['width'] for n in sizes),sizes
                    for y in (13,44,64,112):assert pixel(idle,gap,y)==pixel(baseline,gap,y),(gap,y)
                    island.send('dismiss');wait(lambda:state().get('kind')=='idle');time.sleep(.75);assert geom()['island']['width']==small and geom()['island']['height']==g['island']['height'],geom()
                    points=[]
                    for kind,w in g.items():
                        origin=12 if kind=='left' else width-12-w['width'] if kind=='right' else (width-w['width'])//2
                        for r in w['capsules']:
                            candidates=[(origin+r['x']+x,12+r['y']+y) for x in range(6,max(7,r['width']-6),3) for y in range(8,max(9,r['height']-8),3)]
                            points.append((kind,candidates))
                    if width==1600 and size==16 and alpha==.2:
                        focused=[];software_shots=[]
                        for app_id,title in [('org.selandia.Alpha','Alpha software fixture'),('org.selandia.Omega','Omega software fixture')]:
                            client=start(app_id,[sys.executable,'-B',__file__,'--application',app_id,title])
                            def find_window():
                                return next((window for window in json.loads(session_probe.niri('--json','windows').stdout) if window.get('title')==title),None)
                            wait(find_window)
                            window=find_window()
                            session_probe.niri('action','focus-window','--id',str(window['id'])).check_returncode()
                            wait(lambda:state().get('window_id')==window['id'])
                            assert state()['app_id']==app_id,(app_id,state(),window)
                            data=state();actual=json.loads(session_probe.niri('--json','focused-window').stdout)
                            assert data['window_id']==actual['id'] and data['window_title']==title,(data,actual)
                            software_shots.append(shot(app_id))
                            focused.append(dict(app_id=app_id,title=title,display=data['app_name'],window_id=data['window_id']))
                            stop(client);wait(lambda:state().get('app_id')=='')
                        rect=g['left']['capsules'][-1];a,b=software_shots
                        text_delta=sum(pixel(a,x,y)!=pixel(b,x,y) for x in range(12+rect['x'],12+rect['x']+rect['width']) for y in range(12+rect['y'],12+rect['y']+rect['height']))
                        assert text_delta>15,text_delta
                        (EVID/'focused-software.json').write_text(json.dumps(dict(status='PASS',windows=focused,changed_pixels=text_delta),indent=2))
                    for kind in ('left','island'):
                        w=g[kind]
                        origin=12 if kind=='left' else (width-w['width'])//2
                        # The continuous segment/island surface is the rounded
                        # shape; individual capsules are intentionally inset.
                        for x in (origin+1, origin+w['width']-2):
                            y=12+1
                            assert pixel(idle,x,y)==pixel(baseline,x,y),('rounded corner',kind,x,y)
                    images[width,size,alpha]=(idle,points)
                    results.append(dict(width=width,opacity=alpha,clock_x=clock_x,collapsed=small,expanded=expanded['island']['width'],center_error=error,animation=sizes,click_through=True,font_size=size,capsule_heights=heights,idle_height=g['island']['height']))
                    appearance.apply_settings({**appearance.load_settings(),'reduced_motion':True});island.send('show',kind='volume');time.sleep(.18);assert state()['width']==460 and state()['reduced']
                    stop(p);wait(lambda:not island.endpoint().exists());time.sleep(.25)
                before,points=images[width,size,.2];after,_=images[width,size,1];deltas=[]
                for kind,candidates in points:
                    delta,x,y=max((max(abs(a-b) for a,b in zip(pixel(before,x,y),pixel(after,x,y))),x,y) for x,y in candidates)
                    assert delta>=20,(kind,x,y,delta)
                    deltas.append(dict(kind=kind,x=x,y=y,delta=delta))
                (EVID/f'{width}-{size}-alpha-pixels.json').write_text(json.dumps(deltas,indent=2))
            stop(bg)
        (EVID/'result.json').write_text(json.dumps(dict(status='PASS',layouts=results),indent=2));print(json.dumps(results))
    finally:
        for p in reversed(children):
            if p.poll() is None:stop(p)
        for f in logs:f.close()
if __name__=='__main__':
    if sys.argv[1:]==['--canvas']:canvas()
    elif sys.argv[1:]==['--notifications']:notifications()
    elif sys.argv[1:2]==['--application']:application()
    else:main()
