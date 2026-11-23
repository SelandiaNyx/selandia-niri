"""Prepare setup privately; coordinate deployment, user files and preferences."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import deploy
from transactions import Transaction, file_value, value_fingerprint

sys.path.insert(0, str(deploy.ROOT / "niri/shell"))
import appearance
import application_theme
import language_settings
import ui_assets
import session_settings

THEMES = (*appearance.GENERATED_FILES, "swaync.json")
STATE_FILES = ("appearance.json", "language.json", "language-backup.json", "application-theme.json", session_settings.JOURNAL)


def journal_path():
    return deploy.STATE / "lifecycle-transaction.json"


def targets():
    result = {deploy.ROOT / "niri/theme" / name for name in THEMES}
    result.add(deploy.ROOT / "niri/conf/language.kdl")
    result.add(deploy.CONFIG / "environment.d/90-selandia-language.conf")
    result.update(deploy.STATE / name for name in STATE_FILES)
    result.update(deploy.CONFIG / name for name in application_theme.RELATIVE_FILES)
    owned = session_settings.load(deploy.CONFIG, deploy.STATE / session_settings.JOURNAL)
    result.update(deploy.CONFIG / name for name in owned["files"])
    return result


def transaction(metadata=None):
    managed = targets()
    def allowed(path):
        return path in managed or (path.is_relative_to(deploy.CONFIG) and
                                  session_settings.managed_relative(str(path.relative_to(deploy.CONFIG))))
    return Transaction(journal_path(), {"source": str(deploy.ROOT), "config": str(deploy.CONFIG)},
                       allowed=allowed, metadata=metadata)


def setup_value(path):
    links = (path.is_relative_to(deploy.CONFIG) and
             session_settings.managed_relative(str(path.relative_to(deploy.CONFIG))))
    return file_value(path, allow_links=links)


class PreviewSettings:
    def __init__(self, desktop):
        self.values = {key: desktop.get(key) for key in application_theme.GSETTINGS_KEYS}
        self.users = {key: desktop.user(key) for key in application_theme.GSETTINGS_KEYS}
        self.before = dict(self.users)
        self.before_effective = dict(self.values)
        self.defaults = {key: (desktop.default(key) if hasattr(desktop, "default") else
                              desktop.settings.get_default_value(key).print_(True))
                         for key in application_theme.GSETTINGS_KEYS}

    def get(self, key):
        return self.values[key]

    def user(self, key):
        return self.users[key]

    def set(self, key, value):
        self.users[key] = value
        self.values[key] = self.defaults[key] if value is None else value


@contextmanager
def private_environment(config, state, cache):
    original = dict(os.environ)
    os.environ.update(XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(state.parent), XDG_CACHE_HOME=str(cache))
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def copy_file(source, target):
    if source.exists() or source.is_symlink():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def prepare(action, desktop):
    original = {path: setup_value(path) for path in targets()}
    owned = session_settings.load(deploy.CONFIG, deploy.STATE / session_settings.JOURNAL)
    preview = PreviewSettings(desktop)
    with tempfile.TemporaryDirectory(prefix="selandia-setup-") as temporary:
        private = Path(temporary)
        stage, config, state = private / "project", private / "config", private / "state/selandia-niri"
        stage.mkdir()
        shutil.copytree(deploy.ROOT / "niri", stage / "niri", symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Keep check.sh's existing root-script and tools/tests syntax coverage.
        for directory in ("tools", "tests"):
            if (deploy.ROOT / directory).is_dir():
                shutil.copytree(deploy.ROOT / directory, stage / directory, symlinks=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for script in deploy.ROOT.glob("*.sh"):
            shutil.copy2(script, stage / script.name)
        for name in STATE_FILES + ("wallpaper.json",):
            copy_file(deploy.STATE / name, state / name)
        for relative in owned["files"]:
            copy_file(deploy.CONFIG / relative, config / relative)
        ownership = state / session_settings.JOURNAL
        if ownership.exists():
            owned["config_home"] = str(config)
            ownership.write_text(json.dumps(owned))
        for name in (*application_theme.RELATIVE_FILES, "gtk-3.0/colors.css", "gtk-4.0/colors.css",
                     "environment.d/90-selandia-language.conf"):
            if name in application_theme.RELATIVE_FILES:
                application_theme._safe_parent(deploy.CONFIG / name, deploy.CONFIG)
            copy_file(deploy.CONFIG / name, config / name)
        language_backup = state / "language-backup.json"
        if language_backup.exists():
            data = language_settings._journal(deploy.STATE / "language-backup.json",
                                              language_settings._paths(deploy.CONFIG, deploy.ROOT / "niri"))
            paths = language_settings._paths(config, stage / "niri")
            for key, record in data["files"].items():
                record["path"] = str(paths[key])
            language_backup.write_text(json.dumps(data))
        app_backup = state / "application-theme.json"
        if app_backup.exists():
            data = application_theme._load_journal(deploy.STATE / "application-theme.json", deploy.CONFIG)
            data["config_home"] = str(config)
            app_backup.write_text(json.dumps(data))
        with private_environment(config, state, private / "cache"):
            if action == "install":
                saved = state / "appearance.json"
                if saved.exists():
                    appearance.apply_settings(json.loads(saved.read_text()), base=stage / "niri", state_path=saved)
                language_settings.restore_saved(config_home=config, niri_home=stage / "niri",
                                                state_path=state / "language.json", notify=False)
                ui_assets.write(base=stage / "niri", state_path=saved)
                subprocess.run([str(stage / "check.sh"), "--config"], check=True, timeout=30)
                application_theme.apply_mode(appearance.load_settings(state_path=saved), config_home=config,
                                             state_path=app_backup, desktop=preview, notify=False)
                # Only generated Qt paths change; original backup values remain exact.
                qt = config / application_theme.QT6CT_CONFIG
                qt.write_text(application_theme._set_values(qt.read_text(), "Appearance", "color_scheme_path",
                              [json.dumps(str(deploy.CONFIG / application_theme.QT6CT_PALETTE))]))
            else:
                if language_backup.exists():
                    result = language_settings.restore(config_home=config, niri_home=stage / "niri",
                                                       state_path=state / "language.json")
                    if result["conflicts"]:
                        raise RuntimeError("Language restoration conflicts: " + ", ".join(result["conflicts"]))
                application_theme.restore(config_home=config, state_path=app_backup, desktop=preview, notify=False)
                result = session_settings.restore(config, ownership)
                for relative in result["preserved"]:
                    print("Preserving edited or unrecorded session setting: " + relative)
        if language_backup.exists():
            data = json.loads(language_backup.read_text())
            actual_paths = language_settings._paths(deploy.CONFIG, deploy.ROOT / "niri")
            for key, record in data["files"].items():
                record["path"] = str(actual_paths[key])
            language_backup.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        if app_backup.exists():
            data = json.loads(app_backup.read_text())
            data["config_home"] = str(deploy.CONFIG)
            qt = data["files"].get(application_theme.QT6CT_CONFIG)
            if action == "install" and qt:
                qt["applied_text"] = (config / application_theme.QT6CT_CONFIG).read_text()
                record = qt["keys"]["Appearance"]["color_scheme_path"]
                record["applied"] = json.dumps(str(deploy.CONFIG / application_theme.QT6CT_PALETTE))
            app_backup.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        if ownership.exists():
            data = json.loads(ownership.read_text())
            data["config_home"] = str(deploy.CONFIG)
            ownership.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        replacements = []
        for path, before in original.items():
            if path.is_relative_to(deploy.ROOT / "niri"):
                staged = stage / "niri" / path.relative_to(deploy.ROOT / "niri")
            elif path.is_relative_to(deploy.STATE):
                staged = state / path.relative_to(deploy.STATE)
            else:
                staged = config / path.relative_to(deploy.CONFIG)
            links = path.is_relative_to(deploy.CONFIG) and session_settings.managed_relative(
                str(path.relative_to(deploy.CONFIG)))
            after = file_value(staged, allow_links=links)
            if value_fingerprint(before) != value_fingerprint(after):
                if after:
                    after.pop("mtime", None)
                replacements.append((path, before, after))
    return replacements, preview


def restore_runtime(metadata, desktop):
    for key in reversed(metadata.get("gsettings_started", [])):
        # CLI writes are synchronous; Gio's notification cache can lag behind.
        # Read fresh effective values and undo every durably recorded setter.
        current = desktop.get(key)
        if current not in (metadata["before_effective"][key], metadata["after_effective"][key]):
            raise RuntimeError("Preserving GSettings edited after interrupted setup: " + key)
        desktop.set(key, metadata["before_gsettings"][key])
    if metadata.get("was_active"):
        subprocess.run(["systemctl", "--user", "start", "selandia-niri.target"], check=True, timeout=15)


def recover(desktop=None):
    if not journal_path().exists():
        deploy.recover()
        return
    pending = transaction()
    if pending.data["phase"] == "committed":
        deploy.recover(commit=True)
        pending.finish()
    else:
        deploy.recover(restart=False)
        desktop = desktop or application_theme.DesktopSettings()
        pending.rollback(lambda metadata: restore_runtime(metadata, desktop))
        deploy.reload_units()


def run(action, desktop=None):
    desktop = desktop or application_theme.DesktopSettings()
    with deploy.deployment_lock():
        recover(desktop)
        if action == "install":
            deploy.preflight()
        replacements, preview = prepare(action, desktop)
        was_active = (action == "uninstall" and subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "selandia-niri.target"], check=False, timeout=5).returncode == 0)
        pending = transaction({"before_gsettings": preview.before, "after_gsettings": preview.users,
                               "before_effective": preview.before_effective, "after_effective": preview.values,
                               "gsettings_started": [],
                               "was_active": was_active})
        pending.save()
        try:
            if action == "uninstall":
                deploy.uninstall(defer=True)
            for path, before, after in replacements:
                pending.replace(path, before, after)
            if action == "install":
                deploy.install(defer=True)
            for key, value in preview.users.items():
                if desktop.user(key) != preview.before[key] or desktop.get(key) != preview.before_effective[key]:
                    raise RuntimeError("GSettings changed during setup: " + key)
                if value != preview.before[key]:
                    pending.data["metadata"]["gsettings_started"].append(key)
                    pending.save()
                    desktop.set(key, value)
            # One durable decision covers both journals. Recovery commits the
            # deployment if we die between these two finalization operations.
            pending.data["phase"] = "committed"
            pending.save()
        except BaseException:
            deploy.recover(restart=False)
            pending.rollback(lambda metadata: restore_runtime(metadata, desktop))
            raise
        deploy.recover(commit=True)
        pending.finish()
        deploy.reload_units()
    if action == "install":
        result = language_settings.sync_session()
        for warning in result["warnings"]:
            print(warning, file=sys.stderr)
    for warning in application_theme._notify_qt():
        print(warning, file=sys.stderr)


def main():
    if sys.argv[1:] == ["recover"]:
        with deploy.deployment_lock():
            recover()
    elif sys.argv[1:] in (["install"], ["uninstall"]):
        run(sys.argv[1])
    else:
        raise ValueError("Usage: lifecycle.py install|uninstall|recover")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
