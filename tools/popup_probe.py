#!/usr/bin/env python3
"""Real dialog stacking and pointer delivery over the actual settings window."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import FunctionType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('XDG_STATE_HOME', ''))
if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run only through smoke.py --popup-probe-only')
BASE = Path(os.environ['XDG_CONFIG_HOME']) / 'niri'
BASELINE = os.environ.get('SELANDIA_POPUP_BASELINE')
ARTIFACTS = ROOT / '.validation/panel-dialogs-20261015'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE / 'shell'))


def fixture(kind):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    app = Gtk.Application(application_id='org.selandia.PopupFixture.' + kind)
    def activate(application):
        parent = None
        if kind == 'other':
            parent = Gtk.ApplicationWindow(application=application, title='Other application fixture')
            parent.add(Gtk.Label(label='Private fixture parent'))
            parent.show_all()
        window = Gtk.Dialog(title='Independent popup ' + kind, transient_for=parent, modal=True)
        window.set_application(application)
        window.set_decorated(False); window.set_resizable(False)
        window.set_default_size(440, 260)
        window.get_style_context().add_class('popup-fixture')
        provider = Gtk.CssProvider()
        provider.load_from_data(b'.popup-fixture { background: #ef20a0; color: #101010; }')
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box = window.get_content_area(); box.set_spacing(16); box.set_border_width(24)
        box.pack_start(Gtk.Label(label='Private permission fixture' if kind == 'auth' else 'Other app confirmation'), False, False, 0)
        entry = Gtk.Entry(); entry.set_placeholder_text('Test input'); box.pack_start(entry, False, False, 0)
        button = Gtk.Button(label='Confirm fixture'); button.set_size_request(-1, 70)
        box.pack_end(button, False, False, 0)
        clicked = PRIVATE / ('clicked-' + kind)
        button.connect('clicked', lambda _: clicked.write_text('pointer received'))
        window.show_all(); entry.grab_focus()
        def report():
            x,y = button.translate_coordinates(window, 0, 0)
            (PRIVATE / ('fixture-' + kind + '.json')).write_text(json.dumps({
                'pid':os.getpid(), 'title':window.get_title(),
                'size':[window.get_allocated_width(),window.get_allocated_height()],
                'button':[x + button.get_allocated_width()//2, y + button.get_allocated_height()//2],
                'active':window.is_active(), 'entry_focused':entry.has_focus()}))
            return True
        GLib.timeout_add(50, report)
    app.connect('activate', activate); app.run([])


def main():
    if BASELINE:
        for name in ('shell/panel.py', 'conf/windows.kdl'):
            shutil.copy2(Path(BASELINE) / 'niri' / name, BASE / name)
        time.sleep(.5)
    # Import the copied runtime first; probe helpers otherwise prepend ROOT.
    import panel
    import panel_probe
    import session_probe
    from panel_probe import PanelInteractionTests, Gtk, Gdk, pump_until
    from gi.repository import GdkPixbuf, GLib
    assert session_probe.resize_host_window(int(sys.argv[1]), 1600,
        os.environ['SELANDIA_PROBE_HOST_SOCKET'], height=1000)
    output = session_probe.connected_output()[0]
    session_probe.niri('output', output, 'scale', '1').check_returncode()
    deadline=time.monotonic()+.4; pump_until(lambda:time.monotonic()>=deadline)
    xml=ROOT/'tools/protocols/wlr-virtual-pointer.xml'
    h=PRIVATE/'wlr-virtual-pointer-client.h'; c=PRIVATE/'pointer.c'; pointer=PRIVATE/'pointer'
    for kind, target in (('client-header', h), ('private-code', c)):
        subprocess.run(['wayland-scanner',kind,str(xml),str(target)],check=True,timeout=5)
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client'],text=True,timeout=5).split()
    subprocess.run(['cc','-O2','-I',str(PRIVATE),str(ROOT/'tools/pointer_probe.c'),str(c),'-o',str(pointer),*flags],check=True,timeout=30)
    # Keep helper subprocesses independent of the UI safety mocks. The panel's
    # global subprocess module remains guarded throughout the probe.
    original_run, popen = subprocess.run, subprocess.Popen
    run = FunctionType(original_run.__code__, dict(original_run.__globals__),
                       original_run.__name__, original_run.__defaults__, original_run.__closure__)
    run.__kwdefaults__ = original_run.__kwdefaults__
    PanelInteractionTests.setUpClass()
    test=PanelInteractionTests(); test.setUp()
    children=[]; handles=[]; results=[]
    def windows():
        return json.loads(run(['niri','msg','--json','windows'],capture_output=True,text=True,check=True,timeout=3).stdout)
    def record(title):
        return next((v for v in windows() if v.get('title')==title),None)
    def settle(seconds=.25):
        deadline=time.monotonic()+seconds; pump_until(lambda:time.monotonic()>=deadline)
    def shot(name):
        path=ARTIFACTS/(name+'.png'); before=path.stat().st_mtime_ns if path.exists() else 0
        run(['niri','msg','action','screenshot-screen','--path',str(path),'--show-pointer','false'],check=True,capture_output=True,timeout=5)
        pump_until(lambda:path.exists() and path.stat().st_mtime_ns!=before)
        return GdkPixbuf.Pixbuf.new_from_file(str(path))
    try:
        window=test.make_control('appearance')
        window.color_mode_combo.set_active_id('light')
        window.font_sizes['font'].set_value(17)
        draft=window.draft_appearance()
        settle(.6)
        control=record('Selandia · control')
        if not BASELINE:
            assert control is not None and control['is_floating'], control
            assert not panel.GtkLayerShell.is_layer_window(window)
            assert control['app_id'] == 'org.selandia.Glass', control
            results.append({'control': control})
        for kind in ('auth','other'):
            handle=(ARTIFACTS/(kind+'-fixture.log')).open('w');handles.append(handle)
            child=popen([sys.executable,'-B',__file__,'--fixture',kind],stdout=handle,stderr=handle)
            children.append(child)
            status_path=PRIVATE/('fixture-'+kind+'.json')
            def fixture_state():
                try:return json.loads(status_path.read_text())
                except (OSError,ValueError):return {}
            pump_until(lambda:fixture_state().get('size') and record('Independent popup '+kind),timeout=6)
            item=record('Independent popup '+kind); assert item['is_floating'],item
            w,h=fixture_state()['size']; x=(1600-w)//2; y=(1000-h)//2
            # Position only: do not focus or raise it to manufacture a pass.
            run(['niri','msg','action','move-floating-window','--id',str(item['id']),
                 '--x',str(x),'--y',str(y)],check=True,capture_output=True,timeout=3)
            settle(.4)
            picture=shot(('baseline-' if BASELINE else '')+kind)
            pixels=picture.get_pixels(); stride=picture.get_rowstride();channels=picture.get_n_channels()
            visible=0
            for py in range(y+10,y+h-10,5):
                for px in range(x+10,x+w-10,5):
                    start=py*stride+px*channels
                    if all(abs(a-b)<12 for a,b in zip(pixels[start:start+3],(239,32,160))):visible+=1
            state=fixture_state(); bx,by=state['button']
            run([str(pointer),str(x+bx),str(y+by),'1600','1000','click'],check=True,timeout=5)
            settle(.2)
            clicked=(PRIVATE/('clicked-'+kind)).exists()
            current=record('Independent popup '+kind)
            results.append({'kind':kind,'visible_pixels':visible,'pointer_received':clicked,
                            'focused':bool(current and current['is_focused']),
                            'entry_focused_on_open':state['entry_focused']})
            if BASELINE:
                assert not clicked and visible<20, results[-1]
            else:
                assert clicked and visible>100 and current['is_focused'] and state['entry_focused'],results[-1]
                assert window.draft_appearance()==draft
            child.terminate();child.wait(timeout=5);settle(.2)
        if not BASELINE:
            # Actual Gtk.FontButton creates its own transient dialog.
            window.font_buttons['font'].clicked()
            def font_dialog():
                return next((v for v in Gtk.Window.list_toplevels() if isinstance(v,Gtk.FontChooserDialog) and v.get_visible()),None)
            pump_until(lambda:font_dialog() is not None)
            dialog=font_dialog();pump_until(lambda:record(dialog.get_title()) and record(dialog.get_title())['is_focused'])
            assert dialog.get_transient_for()==window
            settle(.3);shot('font-chooser')
            dialog.response(Gtk.ResponseType.CANCEL);settle(.2)
            assert window.draft_appearance()==draft
            window.select_control_tab('wallpapers')
            card = window.wallpaper_controls
            pump_until(lambda: card.loaded)
            card.playlist_minutes.set_value(3)
            playlist_draft = card.preferences.snapshot()
            page = window.control_stack.get_visible_child_name()

            def check_native(action, dialog_type, name):
                observed, errors = {}, []
                deadline = time.monotonic() + 6
                def inspect():
                    dialog = next((v for v in Gtk.Window.list_toplevels()
                                   if isinstance(v, dialog_type) and v.get_visible()), None)
                    if dialog is None:
                        assert time.monotonic() < deadline, 'Native dialog did not open'
                        return True
                    item = record(dialog.get_title())
                    if not (item and item['is_focused']) and time.monotonic() < deadline:
                        return True
                    try:
                        assert item and item['is_focused'], item
                        assert dialog.get_transient_for() == window
                        assert dialog.get_modal()
                        settle(.2); shot(name)
                        observed.update(focused=True, transient=True, modal=True)
                    except Exception as error:
                        errors.append(error)
                    finally:
                        dialog.response(Gtk.ResponseType.CANCEL)
                    return False
                GLib.timeout_add(50, inspect)
                action()
                if errors: raise errors[0]
                assert observed, name
                assert window.control_stack.get_visible_child_name() == page
                assert window.draft_appearance() == draft
                assert card.preferences.snapshot() == playlist_draft
                results.append({'kind': name, **observed, 'draft_preserved': True})

            # Drive the application's actual synchronous chooser and confirmation
            # paths; cancelling must never reach their write backends.
            for folder in (False, True):
                check_native(lambda: card.choose(folder), Gtk.FileChooserDialog,
                             'folder-chooser' if folder else 'file-chooser')
            card.preferences.rating_filter.set_active_id('mature')
            with patch.object(panel_probe.wallpaper, 'configure_rating_filter') as save:
                check_native(card.preferences.save_filter, Gtk.MessageDialog, 'native-confirmation')
                save.assert_not_called()
            results.append({'native_font_chooser': True, 'draft_preserved': True})
        (ARTIFACTS/('baseline.json' if BASELINE else 'results.json')).write_text(json.dumps(results,indent=2)+'\n')
        print('PASS '+('reproduced old overlay hiding independent popups' if BASELINE else 'floating control: independent dialogs visible, focused and clickable; native dialogs and drafts intact'))
    finally:
        for child in children:
            if child.poll() is None:child.terminate();child.wait(timeout=5)
        test.doCleanups()
        for handle in handles:handle.close()


if sys.argv[1:2]==['--fixture']:fixture(sys.argv[2])
else:main()
