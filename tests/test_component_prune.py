"""Removal keeps daily services usable and can restore a deleted source batch."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'niri/shell'),str(ROOT/'tools')]
import component_preferences as components
import live_update

class PruneTests(unittest.TestCase):
    def test_clock_click_dispatches_calendar_only_in_right_segment(self):
        import bar_backend
        text, _ = bar_backend.render([('test',1600)])
        windows = text.split('(defwindow ')
        self.assertIn(' calendar',windows[2])
        self.assertNotIn(' calendar',windows[1])
        self.assertNotIn(' calendar',windows[3])
        self.assertNotIn('scripts/desktop time',text)

    def test_old_choices_migrate_independently_without_recreating_old_files(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(components,'path',return_value=Path(directory)/'components.json'):
            components.path().write_text(json.dumps({'bar':'waybar','launcher':'fuzzel','terminal':'kitty'}))
            self.assertEqual(components.load(),components.DEFAULTS)
            self.assertEqual(components.daily(restart=False),components.DEFAULTS)
            self.assertEqual(json.loads(components.path().read_text()),components.DEFAULTS)
            for kind,value in (('bar','waybar'),('launcher','fuzzel'),('terminal','kitty')):
                with self.assertRaises(ValueError):components.choose(kind,value,restart=False)

    def test_missing_daily_components_never_execute_deleted_fallback(self):
        installed={'waybar','kitty','fuzzel','anyrun'}
        which=lambda name:name if name in installed else None
        for kind in components.DEFAULTS:
            with self.subTest(kind=kind),self.assertRaisesRegex(RuntimeError,'eww anyrun|alacritty'):
                components.effective(kind,components.DEFAULTS,which)
        self.assertEqual(components.effective('launcher',components.DEFAULTS,lambda name:name),'anyrun')

    def test_manifest_has_required_aur_and_retains_daily_dmenu_lock_notifications(self):
        lines=(ROOT/'packages.txt').read_text().splitlines()
        self.assertFalse({'waybar','kitty'} & set(lines))
        self.assertTrue({'fuzzel','swaync','swaybg','swayidle','swaylock'} <= set(lines))
        for name in ('eww','anyrun'):
            self.assertTrue(any(line.startswith('# required aur '+name+' ') for line in lines))
        for directory in ('waybar','kitty'):
            self.assertFalse(any((ROOT/'niri'/directory).rglob('*')))
        for name in ('waybar.css','waybar.jsonc','kitty.conf'):
            self.assertFalse((ROOT/'niri/theme'/name).exists())

    def test_deletion_publish_rollback_preserves_bytes_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target';source=root/'source'
            target.mkdir();source.mkdir();old=target/'legacy.conf'
            old.write_bytes(b'legacy');old.chmod(0o640)
            (source/'current.conf').write_bytes(b'current')
            update=live_update.Update(target,root/'release')
            update.prepare(source,['current.conf'],remove=['legacy.conf'])
            update.publish();self.assertFalse(old.exists());self.assertTrue((target/'current.conf').exists())
            update.rollback();self.assertEqual(old.read_bytes(),b'legacy')
            self.assertEqual(old.stat().st_mode & 0o777,0o640);self.assertFalse((target/'current.conf').exists())

    def test_recreated_deleted_file_conflicts_before_any_rollback_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target';source=root/'source';target.mkdir();source.mkdir()
            (target/'legacy').write_bytes(b'old');(source/'current').write_bytes(b'new')
            update=live_update.Update(target,root/'release');update.prepare(source,['current'],remove=['legacy']);update.publish()
            (target/'legacy').write_bytes(b'user edit')
            with self.assertRaisesRegex(ValueError,'conflicts'):update.rollback()
            self.assertEqual((target/'legacy').read_bytes(),b'user edit');self.assertEqual((target/'current').read_bytes(),b'new')

    def test_duplicate_or_escape_removal_cannot_delete_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target';source.mkdir();target.mkdir()
            for folder in (source,target):(folder/'one').write_bytes(b'original')
            for remove in (['one'],['../outside'],['@appearance']):
                update=live_update.Update(target,root/('release-'+str(len(list(root.iterdir())))))
                with self.assertRaises(ValueError):update.prepare(source,['one'],remove=remove)
                self.assertEqual((target/'one').read_bytes(),b'original')

    def test_sigkill_after_unlink_restores_deleted_file_from_durable_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target';source=root/'source';target.mkdir();source.mkdir()
            (target/'legacy').write_bytes(b'original')
            update=live_update.Update(target,root/'release');update.prepare(source,[],remove=['legacy'])
            marker=root/'deleted'
            program='''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import live_update
update=live_update.Update(sys.argv[2],sys.argv[3])
real=Path.unlink
def unlink(path,*args,**kwargs):
 real(path,*args,**kwargs)
 if path == update.target/'legacy':
  Path(sys.argv[4]).write_text('deleted')
  while True:time.sleep(.1)
Path.unlink=unlink
update.publish()
'''
            child=subprocess.Popen([sys.executable,'-B','-c',program,str(ROOT/'tools'),str(target),str(root/'release'),str(marker)])
            try:
                deadline=time.monotonic()+5
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(marker.exists());self.assertFalse((target/'legacy').exists())
            finally:
                if child.poll() is None:child.kill()
                child.wait(timeout=3)
            self.assertEqual(update.read()['phase'],'publishing');update.rollback()
            self.assertEqual((target/'legacy').read_bytes(),b'original')
