"""Read-only audit reproducers: no GUI, hardware changes, or user config writes.

This imports current project methods; widgets/application lifecycle are test doubles.
The worker-lifetime case writes only into an automatically deleted /tmp directory.
Run: python3 -B .validation/audit-interactions.py
"""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))

import i18n
import shortcuts
from desktop_controls import SettingsPage


def worker_lifetime():
    source = '''import sys,time,threading
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import panel
class App:
 def quit(self): pass
class Fake:
 alive=True
 pending=set()
 def get_application(self): return App()
started=threading.Event()
path=Path(sys.argv[2])
def task():
 path.write_text('write_one\\n')
 started.set()
 try:
  time.sleep(2)
  path.write_text(path.read_text()+'write_two\\n')
 finally:
  path.write_text(path.read_text()+'finally\\n')
x=Fake()
panel.Panel.work(x,task)
assert started.wait(1)
panel.Panel.on_destroy(x)
# Simulate Gtk.Application.run returning after quit: the script now exits.
'''
    with tempfile.TemporaryDirectory(prefix="selandia-audit-worker-") as tmp:
        marker = Path(tmp) / "phases.txt"
        result = subprocess.run(
            [sys.executable, "-B", "-c", source, str(ROOT / "niri/shell"), str(marker)],
            capture_output=True, text=True, timeout=5,
        )
        phases = marker.read_text().splitlines()
        assert result.returncode == 0, result.stderr
        assert phases == ["write_one"], phases
        return {
            "exit_code": result.returncode,
            "completed_phases": phases,
            "missing_phases": ["write_two", "finally"],
            "scope": "Actual Panel.work/on_destroy; mocked application; temporary-file transaction only",
        }


def refresh_overwrites_draft():
    class Button:
        sensitive = True

        def set_sensitive(self, value):
            self.sensitive = value

    pending = []
    page = SimpleNamespace(
        busy=False, form=Button(), refresh_button=Button(), apply_button=Button(),
        notice=SimpleNamespace(set_text=lambda _: None),
        panel=SimpleNamespace(work=lambda operation, done, failed: pending.append(done)),
        draft_value=16,
    )
    page.populate = lambda state: setattr(page, "draft_value", state["saved"])
    SettingsPage.refresh(page)
    during = {"form_sensitive": page.form.sensitive, "apply_sensitive": page.apply_button.sensitive}
    page.draft_value = 20
    pending[0]({"saved": 16})
    assert all(during.values()) and page.draft_value == 16
    return {"during_refresh": during, "user_entered": 20, "after_read_callback": page.draft_value,
            "scope": "Actual SettingsPage.refresh; delayed callback and widgets are test doubles"}


def shortcut_localization():
    rows = shortcuts.load_shortcuts()
    report = {"total": len(rows)}
    for language in ("en_US", "zh_CN"):
        i18n.set_language(language)
        rendered = [{"keys": item["keys"], "description": i18n.tr_legacy(item["description"])} for item in rows]
        if language == "en_US":
            mixed = [item for item in rendered if re.search(r"[\u3400-\u9fff]", item["description"])]
        else:
            mixed = [item for item in rendered if " / " in item["description"] or "Clipboard only" in item["description"]]
        report[language] = {
            "mixed_count": len(mixed),
            "mixed_examples": mixed[:8],
            "workspace_and_capture": [item for item in rendered if item["keys"] in
                                      ("Super+1", "Super+Shift+1", "Super+PageUp", "Print", "Ctrl+Print")],
        }
        assert mixed
    return report


if __name__ == "__main__":
    print(json.dumps({
        "worker_lifetime": worker_lifetime(),
        "refresh_overwrites_draft": refresh_overwrites_draft(),
        "shortcut_localization": shortcut_localization(),
    }, ensure_ascii=False, indent=2))
