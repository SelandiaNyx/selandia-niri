"""Validate native system settings without changing host services or defaults."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import system_settings as settings


class SystemSettingsTests(unittest.TestCase):
    def setUp(self):
        private = tempfile.TemporaryDirectory(prefix="selandia-system-settings-")
        self.addCleanup(private.cleanup)
        patcher = patch.dict(os.environ, XDG_CONFIG_HOME=str(Path(private.name) / "config"),
                             XDG_STATE_HOME=str(Path(private.name) / "state"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_network_names_with_colons_are_preserved_and_only_uuid_is_executed(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        with patch.object(settings, "run", return_value=identifier + r":Office\: WiFi:802-11-wireless:wlan0") as run:
            profiles = settings.network_state()
            self.assertEqual(profiles[0]["name"], "Office: WiFi")
            settings.activate_connection(identifier, True)
            self.assertEqual(run.call_args.args[0][-3:], ["up", "uuid", identifier])
            run.reset_mock()
            with self.assertRaises(ValueError):
                settings.activate_connection("--help", True)
            run.assert_not_called()

    def test_power_rejects_invalid_values_before_writing(self):
        for value in ({}, dict(settings.DEFAULT_POWER, lock_minutes=True),
                      dict(settings.DEFAULT_POWER, lock_minutes=300),
                      dict(settings.DEFAULT_POWER, screen_minutes=1),
                      dict(settings.DEFAULT_POWER, lock_minutes=0, suspend_minutes=20),
                      dict(settings.DEFAULT_POWER, suspend_minutes=2)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.validate_power(value)

    def test_power_writes_generated_config_and_retains_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "swayidle").mkdir()
            original = root / "swayidle/config"
            original.write_text("# user's original\n")
            state = root / "power.json"
            guard = MagicMock()
            with patch.dict(sys.modules, {"sleep_guard": guard}):
                settings.save_power(dict(settings.DEFAULT_POWER, suspend_minutes=30), base=root, state_path=state)
            config = (root / "swayidle/managed.conf").read_text()
            self.assertIn("timeout 300", config)
            self.assertIn("timeout 600", config)
            self.assertIn("timeout 1800", config)
            self.assertIn("desktop\" sleep'", config)
            self.assertNotIn("lock && systemctl suspend", config,
                             "the timer must reuse the single sleep entry point so a blocked sleep is explained")
            self.assertEqual(original.read_text(), "# user's original\n")
            self.assertEqual(json.loads(state.read_text())["suspend_minutes"], 30)
            guard.apply_timers.assert_called_once_with(True)

    def test_disabled_power_timeouts_emit_no_actions(self):
        config = settings.render_power({key: 0 for key in settings.DEFAULT_POWER})
        self.assertNotIn("timeout", config)

    def test_all_disabled_power_settings_are_not_reported_as_running_timers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            values = dict.fromkeys(settings.DEFAULT_POWER, 0)
            guard = MagicMock()
            with patch.dict(sys.modules, {"sleep_guard": guard}):
                settings.save_power(values, base=root, state_path=state)
            guard.apply_timers.assert_called_once_with(False)
            current = settings.power_state(base=root, state_path=state)
            self.assertEqual(current["settings"], values)
            self.assertFalse(current["timers_enabled"])
            self.assertTrue(current["consistent"])

    def test_enabling_timeouts_after_all_disabled_requests_running_timers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            settings.save_power(dict.fromkeys(settings.DEFAULT_POWER, 0), base=root, state_path=state, reload=False)
            guard = MagicMock()
            with patch.dict(sys.modules, {"sleep_guard": guard}):
                settings.save_power(settings.DEFAULT_POWER, base=root, state_path=state)
            guard.apply_timers.assert_called_once_with(True)
            self.assertTrue(settings.power_state(base=root, state_path=state)["timers_enabled"])

    def test_failed_reload_restores_config_state_permissions_and_previous_timers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            settings.save_power(settings.DEFAULT_POWER, base=root, state_path=state, reload=False)
            config = root / "swayidle/managed.conf"
            config.chmod(0o640)
            previous = (config.read_bytes(), state.read_bytes())
            guard = MagicMock()
            guard.apply_timers.side_effect = [RuntimeError("cannot contact service manager"), None]
            with patch.dict(sys.modules, {"sleep_guard": guard}), self.assertRaisesRegex(RuntimeError, "cannot contact service manager"):
                settings.save_power(dict.fromkeys(settings.DEFAULT_POWER, 0), base=root, state_path=state)
            self.assertEqual((config.read_bytes(), state.read_bytes()), previous)
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertEqual([call.args[0] for call in guard.apply_timers.call_args_list], [False, True])

    def test_failed_first_apply_restores_original_unmanaged_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "swayidle").mkdir()
            original = root / "swayidle/config"
            original.write_text("# manual config\ntimeout 900 'custom-lock'\n")
            state = root / "power.json"
            guard = MagicMock()
            guard.apply_timers.side_effect = [RuntimeError("reload failed"), None]
            with patch.dict(sys.modules, {"sleep_guard": guard}), self.assertRaises(RuntimeError):
                settings.save_power(dict.fromkeys(settings.DEFAULT_POWER, 0), base=root, state_path=state)
            self.assertFalse((root / "swayidle/managed.conf").exists())
            self.assertFalse(state.exists())
            self.assertEqual(original.read_text(), "# manual config\ntimeout 900 'custom-lock'\n")
            self.assertEqual([call.args[0] for call in guard.apply_timers.call_args_list], [False, True])

    def test_failed_recovery_does_not_claim_runtime_was_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            settings.save_power(dict.fromkeys(settings.DEFAULT_POWER, 0), base=root, state_path=state, reload=False)
            guard = MagicMock()
            guard.apply_timers.side_effect = [RuntimeError("first failure"), RuntimeError("recovery failure")]
            with patch.dict(sys.modules, {"sleep_guard": guard}), self.assertRaisesRegex(RuntimeError, "recovery failure"):
                settings.save_power(settings.DEFAULT_POWER, base=root, state_path=state)
            self.assertFalse(settings.power_state(base=root, state_path=state)["timers_enabled"])
            self.assertEqual([call.args[0] for call in guard.apply_timers.call_args_list], [True, False])

    def test_power_state_detects_changed_effective_config_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            settings.save_power(dict.fromkeys(settings.DEFAULT_POWER, 0), base=root, state_path=state, reload=False)
            config = root / "swayidle/managed.conf"
            config.write_text("# User changed this file\ntimeout 300 'lock'\n")
            current = settings.power_state(base=root, state_path=state)
            self.assertTrue(current["timers_enabled"])
            self.assertFalse(current["consistent"])
            self.assertEqual(current["config_path"], str(config))
            self.assertEqual(config.read_text(), "# User changed this file\ntimeout 300 'lock'\n")

    def test_power_state_preserves_unmanaged_configuration_and_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "power.json"
            missing = settings.power_state(base=root, state_path=state)
            self.assertFalse(missing["configured"])
            self.assertTrue(missing["config_error"])
            (root / "swayidle").mkdir()
            config = root / "swayidle/config"
            config.write_text("timeout 300 'custom-lock'\n")
            current = settings.power_state(base=root, state_path=state)
            self.assertFalse(current["configured"])
            self.assertIsNone(current["consistent"])
            self.assertTrue(current["timers_enabled"])
            self.assertFalse(current["config_error"])
            self.assertFalse(state.exists())

    def test_service_changes_are_restricted_to_known_user_units(self):
        with patch.object(settings, "run") as run:
            for key in ("sshd", "../service", "arbitrary.service"):
                with self.assertRaises(ValueError):
                    settings.set_service(key, True)
            run.assert_not_called()
            settings.set_service("clipboard", False)
            self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "mask", "--now",
                "selandia-niri@clipboard-text.service", "selandia-niri@clipboard-image.service"])

    def test_timezone_and_ntp_use_interactive_polkit_with_validated_values(self):
        with patch.object(settings, "timezones", return_value=["Asia/Shanghai", "UTC"]), patch.object(settings, "_timedate") as call:
            with self.assertRaises(ValueError):
                settings.set_timezone("../../etc/passwd")
            call.assert_not_called()
            settings.set_timezone("Asia/Shanghai")
            call.assert_called_once_with("SetTimezone", "(sb)", ("Asia/Shanghai", True))
            settings.set_ntp(True)
            self.assertEqual(call.call_args.args, ("SetNTP", "(bb)", (True, True)))

    def test_default_app_does_not_construct_commands_from_user_values(self):
        with patch.object(settings, "_gio") as gio:
            with self.assertRaises(ValueError):
                settings.set_default_application("browser", "../evil.desktop")
            with self.assertRaises(ValueError):
                settings.set_default_application("arbitrary", "foo.desktop")
            gio.assert_not_called()
            app = gio.return_value.DesktopAppInfo.new.return_value
            app.set_as_default_for_type.return_value = True
            settings.set_default_application("browser", "org.example.Browser.desktop")
            self.assertEqual([call.args[0] for call in app.set_as_default_for_type.call_args_list],
                             ["x-scheme-handler/http", "x-scheme-handler/https"])

    def test_startup_only_creates_niri_entry_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "app.desktop"
            original = "[Desktop Entry]\nType=Application\nName=Example\nExec=example --flag\nOnlyShowIn=KDE;\n"
            source.write_text(original)
            gio = MagicMock()
            gio.DesktopAppInfo.new.return_value.get_filename.return_value = str(source)
            with patch.object(settings, "_gio", return_value=gio):
                settings.add_startup("org.example.应用 App.desktop", home=root)
            target = root / "autostart/selandia-niri-org.example.应用 App.desktop"
            self.assertIn("OnlyShowIn=niri;", target.read_text())
            self.assertEqual(source.read_text(), original)
            settings.toggle_startup(target.name, False, home=root)
            self.assertIn("Hidden=true", target.read_text())
            settings.toggle_startup(target.name, True, home=root)
            self.assertIn("Hidden=false", target.read_text())

    def test_external_startup_shows_hidden_launcher_and_user_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, system = root / "user", root / "system"
            for folder in (home, system):
                (folder / "autostart").mkdir(parents=True)
            source = system / "autostart/org.fcitx.Fcitx5.desktop"
            original = "[Desktop Entry]\nType=Application\nName=Fcitx 5\nExec=fcitx5\nNoDisplay=true\n"
            source.write_text(original)
            entries = settings.external_startup(home=home, config_dirs=[system])
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0]["enabled"])
            self.assertEqual(entries[0]["path"], str(source))
            self.assertEqual(entries[0]["name"], "Fcitx 5")
            override = home / "autostart" / source.name
            override.write_text(original + "Hidden=true\n")
            entries = settings.external_startup(home=home, config_dirs=[system])
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0]["enabled"])
            self.assertEqual(entries[0]["source"], "user")
            self.assertEqual(source.read_text(), original)

    def test_external_startup_respects_niri_visibility_and_managed_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / "autostart"
            directory.mkdir()
            for name, suffix in (("plasma", "OnlyShowIn=KDE;\n"), ("other", "NotShowIn=niri;\n"),
                                 ("niri", "OnlyShowIn=niri;\n"), ("managed", "")):
                (directory / (name + ".desktop")).write_text(
                    "[Desktop Entry]\nType=Application\nName=" + name + "\nExec=true\n" + suffix)
            entries = settings.external_startup(home=home, config_dirs=[], owned_ids={"managed.desktop"})
            self.assertEqual([entry["id"] for entry in entries], ["niri.desktop"])

    def test_unavailable_startup_executable_does_not_break_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / "autostart"
            directory.mkdir()
            (directory / "missing.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Old application\nExec=selandia-nonexistent-test\n"
                "TryExec=/selandia-nonexistent-test\n")
            entries = settings.external_startup(home=home, config_dirs=[])
            self.assertEqual(entries[0]["name"], "Old application")

    def test_startup_refuses_foreign_entries_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "autostart").mkdir()
            target = root / "autostart/selandia-niri-app.desktop"
            target.write_text("[Desktop Entry]\nName=User-owned\nHidden=false\n")
            with self.assertRaises(ValueError):
                settings.toggle_startup(target.name, False, home=root)
            with self.assertRaises(ValueError):
                settings.toggle_startup("../app.desktop", False, home=root)
            self.assertIn("Hidden=false", target.read_text())

    def test_startup_managed_marker_in_comment_does_not_authorize_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "app.desktop"
            source.write_text("[Desktop Entry]\nName=Installed\nExec=example\n")
            (root / "autostart").mkdir()
            target = root / "autostart/selandia-niri-app.desktop"
            original = "[Desktop Entry]\nName=User\n# X-Selandia-Niri-Managed=true\n"
            target.write_text(original)
            gio = MagicMock()
            gio.DesktopAppInfo.new.return_value.get_filename.return_value = str(source)
            with patch.object(settings, "_gio", return_value=gio), self.assertRaises(ValueError):
                settings.add_startup("app.desktop", home=root)
            self.assertEqual(target.read_text(), original)

    def test_startup_refuses_symlink_to_managed_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.desktop"
            content = "[Desktop Entry]\nName=Original\nX-Selandia-Niri-Managed=true\nHidden=false\n"
            original.write_text(content)
            (root / "autostart").mkdir()
            (root / "autostart/selandia-niri-app.desktop").symlink_to(original)
            with self.assertRaises(ValueError):
                settings.toggle_startup("selandia-niri-app.desktop", False, home=root)
            self.assertEqual(original.read_text(), content)

    def test_startup_removal_deletes_only_the_managed_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "autostart").mkdir()
            target = root / "autostart/selandia-niri-app.desktop"
            target.write_text("[Desktop Entry]\nName=Managed\nX-Selandia-Niri-Managed=true\nHidden=false\n")
            other = root / "autostart/selandia-niri-other.desktop"
            other.write_text("[Desktop Entry]\nName=Other\nX-Selandia-Niri-Managed=true\n")
            unrelated = root / "autostart/other.desktop"
            unrelated.write_text("[Desktop Entry]\nName=User\n")
            settings.remove_startup(target.name, home=root)
            self.assertFalse(target.exists())
            self.assertTrue(other.exists())
            self.assertTrue(unrelated.exists())

    def test_startup_removal_refuses_foreign_names_symlinks_and_missing_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "autostart").mkdir()
            foreign = root / "autostart/selandia-niri-app.desktop"
            foreign.write_text("[Desktop Entry]\nName=User-owned\nHidden=false\n")
            original = root / "original.desktop"
            content = "[Desktop Entry]\nName=Original\nX-Selandia-Niri-Managed=true\n"
            original.write_text(content)
            link = root / "autostart/selandia-niri-link.desktop"
            link.symlink_to(original)
            for identifier in (foreign.name, "selandia-niri-link.desktop", "../app.desktop",
                               "selandia-niri-missing.desktop", "other.desktop"):
                with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                    settings.remove_startup(identifier, home=root)
            self.assertIn("Hidden=false", foreign.read_text())
            self.assertTrue(link.is_symlink())
            self.assertEqual(original.read_text(), content)

    def test_startup_removal_reports_a_failed_unlink_instead_of_claiming_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "autostart").mkdir()
            target = root / "autostart/selandia-niri-app.desktop"
            target.write_text("[Desktop Entry]\nName=Managed\nX-Selandia-Niri-Managed=true\n")
            with patch.object(Path, "unlink", side_effect=OSError("read-only file system")):
                with self.assertRaises(RuntimeError) as raised:
                    settings.remove_startup(target.name, home=root)
            self.assertIn("read-only file system", str(raised.exception))

    def test_service_state_distinguishes_masked_from_target_started_static_units(self):
        def result(argv, **_):
            return "masked" if "clipboard" in argv[-1] else "static" if "is-enabled" in argv else "active"
        with patch.object(settings, "run", side_effect=result):
            state = settings.service_state()
        self.assertFalse(state["clipboard"]["enabled"])
        self.assertTrue(state["bar"]["enabled"])
        self.assertTrue(state["bar"]["active"])

    def test_service_state_does_not_treat_empty_failed_reads_as_disabled(self):
        for broken_command in ("is-enabled", "is-active"):
            def result(argv, **_):
                return "" if broken_command in argv else "static" if "is-enabled" in argv else "active"
            with self.subTest(command=broken_command), patch.object(settings, "run", side_effect=result):
                with self.assertRaises(RuntimeError):
                    settings.service_state()

    def test_service_state_keeps_disabled_and_static_units_manageable(self):
        for enabled_state, expected in (("disabled", True), ("static", True), ("masked-runtime", False),
                                        ("not-found", False)):
            with self.subTest(state=enabled_state), patch.object(settings, "run", side_effect=(
                    lambda argv, **_: enabled_state if "is-enabled" in argv else "inactive")):
                state = settings.service_state()
            self.assertEqual(state["bar"]["enabled"], expected)
            self.assertFalse(state["bar"]["active"])

    def test_network_escapes_do_not_change_literal_device_names(self):
        self.assertEqual(settings._nm_fields(r"id:中文 \\ Office\: WiFi:wireless:--"),
                         ["id", "中文 \\ Office: WiFi", "wireless", "--"])


if __name__ == "__main__":
    unittest.main()
