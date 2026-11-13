#!/usr/bin/env python3
"""Pixel/layout regression checks on smoke.py's owned, private Wayland display."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
from functools import lru_cache
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('XDG_STATE_HOME', ''))
sys.path.insert(0, str(ROOT / 'niri/shell'))
import appearance
import session_probe
import panel_probe
from panel_probe import Gtk, Gdk, PanelInteractionTests, pump_until
from gi.repository import GdkPixbuf

ARTIFACTS = ROOT / '.validation/visual-defects-20261010'
BASELINE = os.environ.get('SELANDIA_VISUAL_BASELINE') == '1'
ARTIFACTS = ARTIFACTS / ('before' if BASELINE else 'after')
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def settle(seconds=.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        pump_until(lambda: True)
        time.sleep(.01)


@lru_cache(maxsize=32)
def pixels(pixbuf):
    return pixbuf.get_pixels()


def pixel(pixbuf, x, y):
    offset = int(y) * pixbuf.get_rowstride() + int(x) * pixbuf.get_n_channels()
    return list(pixels(pixbuf)[offset:offset + 3])


def renderings():
    values = dict(appearance.DEFAULTS, font_size=16)
    if BASELINE:
        return json.loads((ROOT/'.validation/visual-defects-20261010/original-render.json').read_text())
    return {str(alpha): appearance.render_files(dict(values, opacity=alpha)) for alpha in (.2,.25,.3,1)}


def install_provider(source, priority=600):
    provider = Gtk.CssProvider(); provider.load_from_data(source.encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, priority)
    return provider


def remove_provider(provider):
    Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), provider)


def text_edges(files):
    """Measure shadow spill outside identical GTK-rasterized glyphs + a 1px edge.

    Render onto transparent pixels so wallpaper details cannot distort the
    edge metric. Native screenshots below separately exercise detailed wallpaper.
    """
    provider = install_provider(files['0.2']['panel.css'])
    transparent = install_provider('window.edge-test {background: transparent;} window.edge-test label {background: transparent; padding: 0;}', 601)
    window = Gtk.OffscreenWindow()
    window.set_visual(Gdk.Screen.get_default().get_rgba_visual())
    window.set_app_paintable(True)
    window.get_style_context().add_class('glass-window')
    window.get_style_context().add_class('edge-test')
    label = Gtk.Label(label='Readable text · 清晰文字 012345')
    label.set_margin_start(24); label.set_margin_end(24)
    label.set_margin_top(16); label.set_margin_bottom(16)
    window.add(label); window.show_all(); settle(.1)
    actual = window.get_pixbuf().copy()
    actual.savev(str(ARTIFACTS/'glyph-shadow.png'),'png',[],[])
    clean = install_provider('window.edge-test label {text-shadow: none;}', 602)
    settle(.1); reference = window.get_pixbuf().copy()
    reference.savev(str(ARTIFACTS/'glyph-reference.png'),'png',[],[])
    assert actual.get_has_alpha() and reference.get_has_alpha()
    def alpha(image,x,y):
        return pixels(image)[y*image.get_rowstride()+x*image.get_n_channels()+3]
    glyph = {(x,y) for y in range(reference.get_height()) for x in range(reference.get_width()) if alpha(reference,x,y)>0}
    edge = {(x+dx,y+dy) for x,y in glyph for dx,dy in ((0,0),(1,0),(-1,0),(0,1),(0,-1))}
    spill = sum(alpha(actual,x,y)>0 for y in range(actual.get_height()) for x in range(actual.get_width()) if (x,y) not in edge)
    core_errors = sum(pixel(actual,x,y)!=pixel(reference,x,y) for x,y in glyph if alpha(reference,x,y)==255)
    result = {'glyph_pixels':len(glyph),'soft_pixels_beyond_one_pixel_outline':spill,
              'opaque_glyph_core_changed':core_errors,'size':[actual.get_width(),actual.get_height()]}
    window.destroy()
    for item in (provider,transparent,clean): remove_provider(item)
    return result




def native_bar(pid, files):
    """Panel text on a detailed static wallpaper; native Eww pixels are checked by bar_island_probe."""
    assert session_probe.resize_host_window(pid,2400,os.environ['SELANDIA_PROBE_HOST_SOCKET'],height=1320)
    output=session_probe.connected_output()[0]
    session_probe.niri('output',output,'scale','1').check_returncode();settle(.3)
    private=Path(os.environ['XDG_CONFIG_HOME'])/'niri'
    (private/'theme/theme.kdl').write_text(files['0.2']['theme.kdl'])
    settle(.35)
    # A dense, high-contrast pattern makes background pollution measurable.
    image=STATE/'detail.svg'
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="1320">'
                     '<defs><pattern id="p" width="24" height="24" patternUnits="userSpaceOnUse">'
                     '<rect width="24" height="24" fill="#102030"/><rect width="12" height="12" fill="#f0e0c0"/>'
                     '<rect x="12" y="12" width="12" height="12" fill="#d0e0f0"/>'
                     '<path d="M0 6h24M0 18h24" stroke="#7898b8"/></pattern></defs>'
                     '<rect width="2400" height="1320" fill="url(#p)"/></svg>')
    wallpaper=subprocess.Popen(['swaybg','-i',str(image),'-m','fill'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        settle(.3);session_probe.screenshot(ARTIFACTS/'wallpaper-only.png')
        reference=GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/'wallpaper-only.png'))
        text_panels = []
        for alpha in ('.2', '.25', '.3'):
            opacity = str(float(alpha))
            (private/'theme/theme.kdl').write_text(files[opacity]['theme.kdl'])
            provider=install_provider(files[opacity]['panel.css'],601)
            test=PanelInteractionTests(methodName='test_control_tabs_metrics_and_unavailable_readings')
            test.setUp()
            try:
                test.appearance_fixture=dict(appearance.DEFAULTS,opacity=float(alpha),font_size=16)
                window=test.make_control('appearance');settle(.5)
                with patch.object(subprocess,'run',real_run),patch.object(subprocess,'Popen',real_popen):
                    session_probe.screenshot(ARTIFACTS/f'text-{opacity}.png')
                # The same actual GTK label, cloned without a shadow, supplies
                # its exact glyph footprint for screenshot edge measurements.
                target=next(label for label in panel_probe.descendants(window)
                            if isinstance(label,Gtk.Label) and label.get_text()=='Surface opacity')
                a=target.get_allocation()
                clone=Gtk.Label(label=target.get_text(),xalign=target.get_xalign(),yalign=target.get_yalign())
                for css in target.get_style_context().list_classes():clone.get_style_context().add_class(css)
                canvas=Gtk.OffscreenWindow();canvas.set_visual(Gdk.Screen.get_default().get_rgba_visual())
                for css in ('glass-window','control-center-window','glyph-mask'):canvas.get_style_context().add_class(css)
                clone.set_size_request(a.width,a.height);canvas.add(clone)
                transparent=install_provider('window.glyph-mask {background: transparent;} window.glyph-mask label {text-shadow:none;}',602)
                canvas.show_all();settle(.1);mask=canvas.get_pixbuf().copy()
                canvas.destroy();remove_provider(transparent)
                target.set_opacity(0);settle(.1)
                with patch.object(subprocess,'run',real_run),patch.object(subprocess,'Popen',real_popen):
                    session_probe.screenshot(ARTIFACTS/f'text-{opacity}-background.png')
                target.set_opacity(1);settle(.1)
                visible=GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/f'text-{opacity}.png'))
                background=GdkPixbuf.Pixbuf.new_from_file(str(ARTIFACTS/f'text-{opacity}-background.png'))
                gx,gy=target.translate_coordinates(window,0,0)
                monitor=Gdk.Display.get_default().get_monitor(0).get_geometry()
                gx+=(monitor.width-window.get_allocated_width())//2
                gy+=(monitor.height-window.get_allocated_height())//2
                glyph={(x,y) for y in range(mask.get_height()) for x in range(mask.get_width())
                       if pixels(mask)[y*mask.get_rowstride()+x*mask.get_n_channels()+3]>0}
                edge={(x+dx,y+dy) for x,y in glyph for dx,dy in ((0,0),(1,0),(-1,0),(0,1),(0,-1))}
                # Ignore <=12-channel noise variation in the historical shader;
                # require a visible text-induced difference beyond a 1px edge.
                tails=sum(max(abs(v-b) for v,b in zip(pixel(visible,gx+x,gy+y),pixel(background,gx+x,gy+y)))>12
                          for y in range(mask.get_height()) for x in range(mask.get_width()) if (x,y) not in edge)
                mask.savev(str(ARTIFACTS/f'text-{opacity}-glyph-mask.png'),'png',[],[])
                text_panels.append({'opacity':float(alpha),'surface_widget_opacity':window.surface.get_opacity(),
                    'window_widget_opacity':window.get_opacity(),'noise':.02 if BASELINE else 0,
                    'native_label_xy':[gx,gy], 'native_soft_tail_pixels':tails,'mask_size':[mask.get_width(),mask.get_height()]})
            finally:
                test.doCleanups();remove_provider(provider)
        return {'text_panels':text_panels,'swaybg_pid':wallpaper.pid}
    finally:
        wallpaper.terminate();wallpaper.wait(timeout=5)


def corners():
    """Real GTK drawing, including theme states; compare corners to a sentinel."""
    screen = Gdk.Screen.get_default()
    providers = []
    snapshots=ROOT/'.validation/visual-defects-20261010'
    sources = ((snapshots/'original-style.css').read_text(),
               (snapshots/'original-control_center.css').read_text(), renderings()['0.2']['panel.css']) if BASELINE else (
               (ROOT/'niri/shell/style.css').read_text(), (ROOT/'niri/shell/control_center.css').read_text(),
               appearance.render_files(dict(appearance.DEFAULTS, opacity=.20))['panel.css'])
    for source in sources:
        provider = Gtk.CssProvider(); provider.load_from_data(source.encode())
        Gtk.StyleContext.add_provider_for_screen(screen, provider, 600)
        providers.append(provider)
    backdrop = Gtk.CssProvider()
    backdrop.load_from_data(b'window.pixel-test, window.pixel-test list, window.pixel-test flowbox { background: #314159; background-image: none; }')
    Gtk.StyleContext.add_provider_for_screen(screen, backdrop, 601)
    providers.append(backdrop)
    window = Gtk.OffscreenWindow()
    for name in ('glass-window', 'control-center-window', 'pixel-test'):
        window.get_style_context().add_class(name)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(16); window.add(box)
    targets = {}
    for name, css in (('navigation', 'settings-navigation'), ('wallpaper-list', 'wallpaper-list')):
        listing = Gtk.ListBox(); listing.get_style_context().add_class(css)
        row = Gtk.ListBoxRow(); row.add(Gtk.Label(label=name)); row.set_size_request(260, 50)
        listing.add(row); listing.select_row(row); box.pack_start(listing, False, False, 0)
        targets[name] = row
    grid = Gtk.FlowBox(); grid.get_style_context().add_class('wallpaper-grid')
    child = Gtk.FlowBoxChild(); child.add(Gtk.Label(label='grid')); child.set_size_request(260, 60)
    grid.add(child); grid.select_child(child); box.pack_start(grid, False, False, 0)
    targets['wallpaper-grid'] = child
    for name, classes in (('tabs', ('control-tabs',)), ('tile', ('tile', 'active')),
                          ('quick-details', ('quick-details',)), ('quick-tile', ('quick-tile', 'active'))):
        button = Gtk.ToggleButton(label=name); button.set_active(True); button.set_size_request(260, 50)
        parent = Gtk.Box(); parent.pack_start(button, True, True, 0)
        if name == 'tabs': parent.get_style_context().add_class('control-tabs')
        else:
            for css in classes: button.get_style_context().add_class(css)
        box.pack_start(parent, False, False, 0); targets[name] = button
    spin = Gtk.SpinButton.new_with_range(1,180,1)
    spin.set_size_request(260,50);spin.set_state_flags(Gtk.StateFlags.ACTIVE,False)
    box.pack_start(spin,False,False,0);targets['spinbutton-active']=spin
    window.show_all(); settle()
    for widget in targets.values(): widget.set_opacity(0)
    settle(.05)
    reference = window.get_pixbuf().copy()
    for widget in targets.values(): widget.set_opacity(1)
    settle(.05)
    image = window.get_pixbuf(); image.savev(str(ARTIFACTS/'state-corners.png'), 'png', [], [])
    results = {}
    for name, widget in targets.items():
        x, y = widget.translate_coordinates(window, 0, 0)
        a = widget.get_allocation(); context = widget.get_style_context()
        values = [pixel(image, x+dx, y+dy) for dx,dy in ((0,0),(a.width-1,0),(0,a.height-1),(a.width-1,a.height-1))]
        positions = ((0,0),(a.width-1,0),(0,a.height-1),(a.width-1,a.height-1))
        expected = [pixel(reference, x+dx, y+dy) for dx,dy in positions]
        results[name] = {'radius': context.get_property('border-radius', context.get_state()),
                         'size': [a.width, a.height], 'corners': values,
                         'background': expected,
                         'passed': all(max(abs(v[i]-e[i]) for i in range(3)) <= 2 for v,e in zip(values,expected))}
    window.destroy()
    for provider in providers: Gtk.StyleContext.remove_provider_for_screen(screen, provider)
    return results


def layouts(pid):
    saved_run, saved_popen = subprocess.run, subprocess.Popen
    host = os.environ['SELANDIA_PROBE_HOST_SOCKET']
    PanelInteractionTests.app.reload_theme()
    results = []
    for case, width, scale, height in (('wide', 2400, 1, 1320), ('narrow', 900, 1.5, 1000)):
        assert session_probe.resize_host_window(pid, width, host, height=height)
        output = session_probe.connected_output()[0]
        session_probe.niri('output', output, 'scale', str(scale)).check_returncode(); settle(.5)
        test = PanelInteractionTests(methodName='test_control_tabs_metrics_and_unavailable_readings')
        test.setUp()
        try:
            test.appearance_fixture = dict(appearance.DEFAULTS, opacity=.20, font_size=16)
            window = test.make_control('wallpapers'); card = window.wallpaper_controls
            pump_until(lambda: card.loaded)
            for index in range(7):
                card.add_item(dict(test.wallpaper_fixture, path=f'/probe/{index}', title=f'Wallpaper {index+1}'))
            card.grid.show_all(); card.list.show_all(); card.set_view('list'); settle(.6)
            row = card.list.get_children()[0]; row_height = row.get_allocated_height()
            viewport = card.scroll.get_vadjustment().get_page_size()
            # A nested viewport may allocate 180px but be entirely clipped by
            # the page's outer scroll. Count the actual on-screen intersection.
            sx, sy = card.scroll.translate_coordinates(window, 0, 0)
            visible_top, visible_bottom = sy, sy + card.scroll.get_allocated_height()
            ancestor = card.scroll.get_parent()
            while ancestor is not None and ancestor is not window:
                if isinstance(ancestor, (Gtk.Viewport, Gtk.ScrolledWindow)):
                    ax, ay = ancestor.translate_coordinates(window, 0, 0)
                    visible_top = max(visible_top, ay)
                    visible_bottom = min(visible_bottom, ay + ancestor.get_allocated_height())
                ancestor = ancestor.get_parent()
            viewport = max(0, visible_bottom - visible_top)
            row_y = row.get_allocation().y
            fully_visible = sum(r.translate_coordinates(window, 0, 0)[1] >= visible_top and
                r.translate_coordinates(window, 0, 0)[1] + r.get_allocated_height() <= visible_bottom
                for r in card.list.get_children())
            results.append({'case':case, 'panel':[window.get_allocated_width(),window.get_allocated_height()],
                'row_height':row_height, 'viewport':viewport, 'row_y':row_y, 'fully_visible':fully_visible,
                'surface_opacity':window.surface.get_opacity(), 'passed':fully_visible >= 2})
            with patch.object(subprocess,'run',saved_run), patch.object(subprocess,'Popen',saved_popen):
                session_probe.screenshot(ARTIFACTS/(case+'-wallpapers.png'))
        finally: test.doCleanups()
    return results


def main():
    if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not STATE.name.startswith('selandia-smoke-'):
        raise SystemExit('Run only through tools/smoke.py --visual-defects-probe-only')
    Gtk.Settings.get_default().set_property('gtk-theme-name', 'Breeze-Dark')
    files=renderings()
    global real_run,real_popen
    real_run,real_popen=subprocess.run,subprocess.Popen
    results = {'theme': Gtk.Settings.get_default().get_property('gtk-theme-name'), 'corners':corners(),
               'glyph_edges':text_edges(files),
               }
    if BASELINE:
        # Recreate the old page layout from immutable source snapshots. All
        # backend operations remain mocked; BASE stays inside the temporary copy.
        for name in ('wallpaper_controls','panel'):
            module=types.ModuleType('baseline_'+name)
            module.__file__=str(ROOT/'niri/shell'/(name+'.py'))
            source=(ROOT/'.validation/visual-defects-20261010'/('original-'+name+'.py')).read_text()
            exec(compile(source,module.__file__,'exec'),module.__dict__)
            if name=='wallpaper_controls':sys.modules[name]=module
            else:panel_probe.Panel=module.Panel
    PanelInteractionTests.setUpClass()
    results['native_bar']=native_bar(int(sys.argv[1]),files)
    results['layouts']=layouts(int(sys.argv[1]))
    (ARTIFACTS/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2),flush=True)
    if not BASELINE:
        assert all(v['passed'] for v in results['corners'].values()), 'Selected/checked corners are square'
        assert all(v['passed'] for v in results['layouts']), 'Library displays fewer than two complete rows'
        for values in results['native_bar']['text_panels']:
            assert values['surface_widget_opacity'] == values['window_widget_opacity'] == 1
            assert values['native_soft_tail_pixels'] == 0, 'Native screenshot retains a soft text halo'
        assert results['glyph_edges']['soft_pixels_beyond_one_pixel_outline']==0, 'Soft text-shadow persists'


if __name__ == '__main__': main()
