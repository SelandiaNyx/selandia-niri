"""Notification labels are localized; generation never revives removed components."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
BASE=Path(__file__).resolve().parents[1]/'niri'
sys.path.insert(0,str(BASE/'shell'))
import i18n
import ui_assets
import appearance

class UiAssetsTests(unittest.TestCase):
    def setUp(self):self.addCleanup(i18n.set_language,None)
    def test_each_language_replaces_only_owned_display_strings(self):
        original=json.loads((BASE/'swaync/config.json').read_text())
        for lang,title in (('en_US','Notifications'),('zh_CN','通知')):
            i18n.set_language(lang)
            result=ui_assets.render(base=BASE)
            self.assertEqual(set(result),{'swaync.json'})
            notification=result['swaync.json']
            self.assertEqual(notification['widget-config']['title']['text'],title)
            self.assertEqual(notification['widgets'],original['widgets'])
            self.assertEqual(notification['widget-config']['mpris'],original['widget-config']['mpris'])
    def test_generation_preserves_source_and_rust_theme(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'niri';shutil.copytree(BASE,base)
            state=Path(directory)/'state/appearance.json'
            appearance.apply_settings({'font_size':20,'color_mode':'light'},base=base,state_path=state)
            before={p.name:p.read_bytes() for p in (base/'theme').iterdir()}
            i18n.set_language('zh_CN');ui_assets.write(base=base,state_path=state)
            self.assertEqual(json.loads((base/'theme/swaync.json').read_text())['text-empty'],'暂无通知')
            for name in appearance.GENERATED_FILES:self.assertEqual((base/'theme'/name).read_bytes(),before[name])
            self.assertEqual((base/'swaync/config.json').read_bytes(),(BASE/'swaync/config.json').read_bytes())
            self.assertFalse((base/'theme/waybar.jsonc').exists())
