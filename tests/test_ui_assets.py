"""Generated language labels preserve source commands, metadata and placeholders."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "niri"
sys.path.insert(0, str(BASE / "shell"))
import i18n
import ui_assets


class UiAssetsTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, None)
        locales = patch.object(ui_assets, "available_locales", return_value=["C", "zh_CN.utf8", "en_US.utf8"])
        self.locales = locales.start()
        self.addCleanup(locales.stop)

    def test_each_language_replaces_only_owned_display_strings(self):
        source_bar = json.loads((BASE / "waybar/config.jsonc").read_text())
        source_notifications = json.loads((BASE / "swaync/config.json").read_text())
        for language, title, other in (("en_US", "Notifications", "通知"), ("zh_CN", "通知", "Notifications")):
            with self.subTest(language=language):
                i18n.set_language(language)
                values = ui_assets.render(base=BASE)
                bar, notifications = values["waybar.jsonc"], values["swaync.json"]
                self.assertEqual(bar["clock"]["locale"], language + ".UTF-8")
                self.assertEqual(notifications["widget-config"]["title"]["text"], title)
                self.assertNotIn(other, notifications["widget-config"]["title"]["text"])
                for key, value in source_bar.items():
                    if isinstance(value, dict):
                        for field, old in value.items():
                            if not field.startswith("tooltip-format"):
                                self.assertEqual(bar[key][field], old, f"{key}.{field}")
                    else:
                        self.assertEqual(bar[key], value)
                for field in ("{desc}", "{volume}"):
                    self.assertIn(field, bar["pulseaudio"]["tooltip-format"])
                for field in ("{ifname}", "{ipaddr}", "{essid}"):
                    self.assertIn(field, bar["network"]["tooltip-format"])
                self.assertEqual(notifications["widgets"], source_notifications["widgets"])
                self.assertEqual(notifications["widget-config"]["mpris"], source_notifications["widget-config"]["mpris"])

    def test_missing_clock_locale_uses_safe_fallback(self):
        i18n.set_language("zh_CN")
        self.locales.return_value = ["C"]
        self.assertEqual(ui_assets.render(base=BASE)["waybar.jsonc"]["clock"]["locale"], "C")

    def test_generation_keeps_source_templates_and_emits_valid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for source in ("waybar/config.jsonc", "swaync/config.json"):
                target = base / source
                target.parent.mkdir(parents=True)
                shutil.copyfile(BASE / source, target)
            i18n.set_language("zh_CN")
            ui_assets.write(base=base)
            self.assertEqual(json.loads((base / "theme/swaync.json").read_text())["text-empty"], "暂无通知")
            for source in ("waybar/config.jsonc", "swaync/config.json"):
                self.assertEqual((base / source).read_bytes(), (BASE / source).read_bytes())


if __name__ == "__main__":
    unittest.main()
