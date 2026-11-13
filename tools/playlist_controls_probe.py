#!/usr/bin/env python3
"""Real resident rotation, atomic handoff/fade/SIGKILL, plus wide/narrow GTK UI."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=Path(os.environ.get('XDG_STATE_HOME',''))
if os.environ.get('SELANDIA_PRIVATE_PROBE')!='1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run through tools/smoke.py --playlist-controls-probe-only')
BASE=Path(os.environ['XDG_CONFIG_HOME'])/'niri'
sys.path.insert(0,str(BASE/'shell'))
import appearance
import i18n
import wallpaper as w
import wallpaper_playlist as policy
import wallpaper_remote as remote
import wallpaper_audio
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

ARTIFACTS=Path(os.environ.get('SELANDIA_WALLPAPER_ARTIFACTS', str(ROOT/'.validation/wallpaper-controls-20261010/probe')))
ARTIFACTS.mkdir(parents=True,exist_ok=True)


def wait(predicate,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('private probe condition timed out')


def shot(name):
    path=ARTIFACTS/name
    previous=path.stat().st_mtime_ns if path.exists() else 0
    subprocess.run(['niri','msg','action','screenshot-screen','--path',str(path),'--show-pointer','false'],
                   check=True,capture_output=True,timeout=5)
    wait(lambda:path.exists() and path.stat().st_mtime_ns!=previous)
    image=GdkPixbuf.Pixbuf.new_from_file(str(path));x,y=image.get_width()//2,image.get_height()//2
    offset=y*image.get_rowstride()+x*image.get_n_channels()
    return list(image.get_pixels()[offset:offset+3])


def children(pid):
    try:return [int(value) for value in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]
    except FileNotFoundError:return []


def main():
    i18n.set_language('en_US')
    appearance.apply_settings({**appearance.load_settings(),'wallpaper_colors':False})
    paths=[]
    for name,color,rating in (('Red',0xe04040ff,'Everyone'),('Blue',0x2040d0ff,'G'),('Green',0x30b060ff,'General'),('Hidden',0xa040a0ff,'Mature')):
        directory=PRIVATE/name;directory.mkdir()
        path=directory/'image.png';image=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,96,54)
        image.fill(color);image.savev(str(path),'png',[],[])
        (directory/'project.json').write_text(json.dumps({'title':name,'type':'image','file':'image.png','preview':'image.png','contentrating':rating}))
        paths.append(str(directory))
    original_metadata={path:(Path(path)/'project.json').read_bytes() for path in paths}
    items=[{'path':path,'mode':'preview'} for path in paths]
    # A real old flat file exercises migration at service startup.
    old={'selection':dict(items[0],fallback=w.describe(paths[0])['preview']),'audio':{'muted':True,'volume':27},
         'roots':[str(PRIVATE)],'playlist':{'enabled':False,'items':items,'order':'sequential','trigger':'timer','minutes':1}}
    w.save_settings(old)
    if os.environ.get("SELANDIA_PLAYLIST_UI_ONLY") == "1":
        result = ui(sys.argv[1], paths)
        (ARTIFACTS/"ui-results.json").write_text(json.dumps(result,indent=2)+"\n")
        print("PASS wide/narrow named-playlist, playback and library GTK layouts")
        return
    handle=(ARTIFACTS/'runtime.log').open('w');child=None;owned=[]
    result={}
    def start():
        process=subprocess.Popen([sys.executable,'-B',str(BASE/'shell/wallpaper.py'),'run'],
                                  stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
        wait(lambda:remote.path().exists() and len(children(process.pid))==2)
        return process
    def terminate(process,kill=False):
        owned=children(process.pid)
        if process.poll() is None:
            os.kill(process.pid,signal.SIGKILL if kill else signal.SIGTERM)
            process.wait(timeout=8)
        if kill:
            for pid in owned:
                try:os.killpg(pid,signal.SIGTERM)
                except ProcessLookupError:pass
    def events():
        return [json.loads(line) for line in (ARTIFACTS/'runtime.log').read_text().splitlines() if line.startswith('{"wallpaper_playlist":')]
    try:
        child=start();identity=wallpaper_audio.process_identity(child.pid)
        migrated=w.load_settings();assert migrated['playlist']['seconds']==60
        assert len(migrated['playlist']['items'])==4 and migrated['audio']==old['audio']
        # A legacy local label cannot unhide the author's Mature project.
        w.set_ratings([paths[3]],'everyone')
        w.manage_playlists('duplicate',title='Weighted shuffle')
        settings=w.load_settings();value={**settings['playlist'],'enabled':True,'order':'shuffle','seconds':1}
        w.configure_playlist(value)
        wait(lambda:len([e for e in events() if e['wallpaper_playlist']=='switched'])>=6,timeout=25)
        switched=[e for e in events() if e['wallpaper_playlist']=='switched'][:6]
        assert all(e['path']!=paths[3] and e['rating']=='everyone' for e in switched)
        assert len({e['path'] for e in switched[:3]})==3 and len({e['path'] for e in switched[3:]})==3
        assert wallpaper_audio.process_identity(child.pid)==identity
        assert len(children(child.pid))==2
        assert all(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]!='Z' for pid in children(child.pid))
        result['shuffle']={'events':switched,'same_supervisor':True,'children':2,'zombies':0}
        assert all((Path(path)/'project.json').read_bytes()==data for path,data in original_metadata.items())
        result['project_ratings']={'source':'project.json','legacy_override_ignored':True,'metadata_unchanged':True}
        value={**w.load_settings()['playlist'],'enabled':False};w.configure_playlist(value)
        w.activate(paths[0],'preview')
        w.configure_display({'mode':'fill','transition':'fade','duration':2})
        # Changing only fade options keeps the current rendered frame.
        failures=[]
        thread=threading.Thread(target=lambda:call_activate(paths[1],failures));thread.start()
        wait(lambda:list(Path(os.environ['XDG_RUNTIME_DIR']).glob('selandia-wallpaper-*/*.fade.begin')))
        time.sleep(.25);first=shot('fade-early.png')
        time.sleep(.5);middle=shot('fade-middle.png')
        thread.join(timeout=5);assert not thread.is_alive() and not failures,failures
        late=shot('fade-finished.png')
        assert first[0]>middle[0]>late[0] and first[2]<middle[2]<late[2],(first,middle,late)
        assert wallpaper_audio.process_identity(child.pid)==identity
        assert len(children(child.pid))==2
        result['fade']={'early':first,'middle':middle,'finished':late,'same_supervisor':True,'children_after':2}
        # Fail readiness of an unsupported project, preserving old selection.
        before=w.load_settings()
        try:w.activate(str(PRIVATE/'absent.png'),'preview')
        except RuntimeError:pass
        else:raise AssertionError('invalid selection was accepted')
        assert w.load_settings()==before
        # Kill the service while a real overlay is active: journal rolls back both
        # selection and shuffle remainder. Private children are explicitly cleaned.
        failures=[];thread=threading.Thread(target=lambda:call_activate(paths[0],failures));thread.start()
        wait(lambda:list(Path(os.environ['XDG_RUNTIME_DIR']).glob('selandia-wallpaper-*/*.fade.begin')))
        assert (w.state_dir()/'wallpaper-transition.json').exists()
        terminate(child,kill=True);thread.join(timeout=5);assert not thread.is_alive()
        child=start()
        assert w.load_settings()==before
        assert not (w.state_dir()/'wallpaper-transition.json').exists()
        assert any(e['wallpaper_playlist']=='recovered' for e in events())
        result['sigkill']={'recovered':True,'preferences_preserved':True}
        # A short finite video uses actual mpv EOF; seconds do not determine it.
        video=PRIVATE/'finite.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15:duration=2',
                        '-c:v','libx264',str(video)],check=True,timeout=10)
        w.configure_display({'mode':'fit','transition':'instant','duration':.6})
        w.activate(str(video),'live')
        config={**w.load_settings()['playlist'],'items':[{'path':str(video),'mode':'live'}],
                'enabled':True,'order':'sequential','trigger':'finished','seconds':10800}
        w.configure_playlist(config)
        offset=len(events())
        wait(lambda:any(e['wallpaper_playlist']=='switched' and e['trigger']=='finished' for e in events()[offset:]),timeout=9)
        result['eof']={'switched_before_timer':True,'timer_seconds':10800}
        # Empty and fully filtered playlists remain resident and quiet.
        w.configure_playlist({**config,'items':[]});offset=len(events());time.sleep(1.5)
        assert not any(e['wallpaper_playlist']=='switched' for e in events()[offset:])
        result['empty']={'idle':True}
        w.configure_playlist({**config,'enabled':False,'items':items})
        result['display_modes']=display_modes(paths)
        w.configure_display({'mode':'fill','transition':'instant','duration':.6});w.activate(paths[0],'preview')
        terminate(child);child=None
        (ARTIFACTS/"backend-results.json").write_text(json.dumps(result,indent=2)+"\n")
        result['gtk']=ui(sys.argv[1],paths)
        (ARTIFACTS/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('PASS named playlist migration, resident 2 shuffle cycles, Mature filtering, true fade pixels, SIGKILL rollback, video EOF, empty idle, wide/narrow GTK',flush=True)
    finally:
        if child is not None:terminate(child)
        handle.close()


def display_modes(paths):
    pattern=PRIVATE/'display-pattern.png'
    image=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,96,54);image.fill(0xe04040ff)
    half=GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB,False,8,48,54);half.fill(0x2040d0ff)
    half.copy_area(0,0,48,54,image,48,0);image.savev(str(pattern),'png',[],[])
    w.configure_display({'mode':'fill','transition':'instant','duration':.6});w.activate(str(pattern),'preview')
    results=[]
    for mode in ('fill','cover','stretch','fit','center','tile'):
        w.configure_display({'mode':mode,'transition':'instant','duration':.6});shot('display-'+mode+'.png')
        captured=GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/('display-'+mode+'.png')))
        width,height=captured.get_width(),captured.get_height()
        def pixel(x,y):
            offset=y*captured.get_rowstride()+x*captured.get_n_channels()
            return list(captured.get_pixels()[offset:offset+3])
        red,blue,black=[224,64,64],[32,64,208],[16,21,34]
        if mode in ('fill','cover','stretch'):
            assert pixel(width//4,10)==red and pixel(width*3//4,10)==blue
        elif mode=='fit':
            assert pixel(width//4,0)==black and pixel(width//4,height//2)==red
        elif mode=='center':
            assert pixel(0,0)==black and pixel(width//2-16,height//2)==red and pixel(width//2+16,height//2)==blue
            # Stop only our current static renderer; its guard must match center.
            live=children_of_static_renderer()
            os.kill(live,signal.SIGTERM);time.sleep(.3);shot('display-center-fallback.png')
            fallback=GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/'display-center-fallback.png'))
            assert list(fallback.get_pixels()[:3])==black
            offset=(height//2)*fallback.get_rowstride()+(width//2+16)*fallback.get_n_channels()
            assert list(fallback.get_pixels()[offset:offset+3])==blue
        else:
            assert pixel(20,20)==red and pixel(68,20)==blue and pixel(116,20)==red
        results.append({'mode':mode,'passed':True,'dimensions':[width,height]})
    return results


def children_of_static_renderer():
    # The current service is the peer of our same-session control socket. Both
    # children have private fixture paths; choose the pattern renderer, not guard.
    import socket,struct
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.connect(str(remote.path()))
        pid,_,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    candidates=[]
    for child in children(pid):
        command=Path(f'/proc/{child}/cmdline').read_bytes()
        if str(PRIVATE/'display-pattern.png').encode() in command:candidates.append(child)
    assert len(candidates)==1,candidates
    return candidates[0]


def call_activate(path,failures):
    try:w.activate(path,'preview')
    except Exception as error:failures.append(str(error))


def ui(compositor,paths):
    import panel_probe,session_probe
    from panel_probe import PanelInteractionTests,pump_until,Gdk,Gtk
    PanelInteractionTests.setUpClass();result=[]
    real_run,real_popen=subprocess.run,subprocess.Popen
    def ui_shot(name):
        # Native xdg windows need their configure/frame callbacks dispatched.
        # A synchronous screenshot wait alone can capture only the background.
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            settle = time.monotonic() + .2
            pump_until(lambda: time.monotonic() >= settle)
            with patch.object(subprocess,'run',real_run),patch.object(subprocess,'Popen',real_popen):
                shot(name)
            picture = GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/name))
            pixels = picture.get_pixels(); channels = picture.get_n_channels(); stride = picture.get_rowstride()
            colors = {tuple(pixels[y*stride+x*channels:y*stride+x*channels+3])
                      for y in range(0,picture.get_height(),8) for x in range(0,picture.get_width(),8)}
            if len(colors) > 100:
                return
        raise AssertionError('Control center was not visibly rendered: '+name)
    for size,width,scale,height in (('wide',2400,1,1320),('narrow',900,1.5,1000)):
        assert session_probe.resize_host_window(int(compositor),width,os.environ['SELANDIA_PROBE_HOST_SOCKET'],height=height)
        output=session_probe.connected_output()[0];session_probe.niri('output',output,'scale',str(scale)).check_returncode()
        deadline=time.monotonic()+.5
        while time.monotonic()<deadline:
            panel_probe.drain();time.sleep(.01)
        for language in ('en_US','zh_CN'):
            case=size+'-'+language
            test=PanelInteractionTests(methodName='test_named_playlist_drafts_switch_copy_rename_and_save_all');test.setUp()
            i18n.set_language(language)
            try:
                window=test.make_control('wallpapers');card=window.wallpaper_controls
                pump_until(lambda:card.loaded)
                for path in paths:card.add_item(w.describe(path))
                card.grid.show_all();card.list.show_all()
                card.set_view('list');pump_until(lambda:card.scroll.get_vadjustment().get_page_size()>=148)
                row=card.items[paths[0]]['list'];card.list.select_row(row)
                assert 'Wallpaper Engine' in card.preferences.rating_summary.get_text()
                viewport=card.scroll.get_vadjustment().get_page_size()
                assert viewport//row.get_allocated_height()>=2,(case,viewport,row.get_allocated_height())
                monitor=Gdk.Display.get_default().get_monitor(0).get_geometry()
                assert window.get_allocated_width()<=monitor.width,(case,'width',window.get_allocated_width(),monitor.width)
                assert window.get_allocated_height()<=monitor.height,(case,'height',window.get_allocated_height(),monitor.height)
                assert card.workspace_pane.get_orientation()==(Gtk.Orientation.HORIZONTAL if window.panel_width>=1000 else Gtk.Orientation.VERTICAL)
                card.playlist_add();card.playlist_minutes.set_value(17)
                card.preferences.display.set_active_id('stretch')
                selected=card.selected
                reached=[]
                for name,widget in (('display',card.preferences.display),('rating',card.preferences.rating_filter),('playlist',card.preferences.names)):
                    assert widget.is_ancestor(card.details)
                    y=widget.translate_coordinates(card.details,0,0)[1]
                    adjustment=card.details_scroll.get_vadjustment()
                    adjustment.set_value(max(0,min(y,adjustment.get_upper()-adjustment.get_page_size())))
                    deadline=time.monotonic()+.15
                    pump_until(lambda:time.monotonic()>=deadline)
                    top=widget.translate_coordinates(card.details_scroll,0,0)[1]
                    assert top>=0 and top+widget.get_allocated_height()<=card.details_scroll.get_allocated_height(),(case,name,top,widget.get_allocated_height(),card.details_scroll.get_allocated_height())
                    assert card.library.get_mapped() and card.details_scroll.get_mapped()
                    assert card.selected==selected and card.playlist_minutes.get_value_as_int()==17
                    ui_shot(case+'-'+name+'.png')
                    reached.append(name)
                card.set_view('grid');card.details_scroll.get_vadjustment().set_value(0)
                panel_probe.drain();time.sleep(.15)
                ui_shot(case+'-grid.png')
                test.wallpaper_apply.assert_not_called()
                result.append({'case':case,'panel_width':window.panel_width,'allocated':[window.get_allocated_width(),window.get_allocated_height()],
                               'library_viewport':viewport,'row_height':row.get_allocated_height(),'visible_rows':int(viewport//row.get_allocated_height()),
                               'same_page_controls':reached,'selection_and_draft_preserved':True})
            finally:test.doCleanups()
    return result


if __name__=='__main__':main()
