"""Check actual shortcut coverage and AI transport boundaries without live API calls."""
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import ai_backend as ai
import shortcuts


class ShortcutTests(unittest.TestCase):
    def test_every_real_binding_has_a_searchable_entry(self):
        text = (shortcuts.BASE / "conf/binds.kdl").read_text()
        expected = {line.split()[0].replace("Mod", "Super").replace("Page_", "Page")
                    for line in text.splitlines() if re.match(r"^    \w.*\{", line)}
        rows = shortcuts.load_shortcuts()
        self.assertTrue(expected <= {row["keys"] for row in rows})
        self.assertGreater(len(expected), 100)
        self.assertFalse([row for row in rows if not row["description"][0] or not row["description"][1]])
        self.assertFalse([row for row in rows if row["category"] == ("Custom", "自定义")])

    def test_local_override_and_hidden_alias_remain_discoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "conf").mkdir()
            (base / "conf/binds.kdl").write_text('binds {\n Mod+A hotkey-overlay-title=null { close-window; }\n}\n')
            (base / "conf/local.kdl").write_text('binds {\n Mod+A { toggle-overview; }\n}\n')
            with patch.object(shortcuts, "BASE", base):
                rows = [row for row in shortcuts.load_shortcuts() if row["keys"] == "Super+A"]
            self.assertEqual(len(rows), 1)
            self.assertIn("overview", rows[0]["description"][0])

    def test_unmodified_keys_and_comments(self):
        source = '''binds {
 F1 { show-hotkey-overlay; }
 /* Mod+B { close-window; } */
 // Mod+C { close-window; }
 Mod+D { spawn "https://example.org"; } // comment
}
window-rule { open-floating true; }
'''
        rows = [match[1] for section in shortcuts.binding_sections(source) for match in shortcuts.NODE.finditer(section)]
        self.assertEqual(rows, ["F1", "Mod+D"])


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(ai.DEFAULTS, model="installed-model")

    def response(self, data):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        return opener

    def test_ollama_chat_sends_only_supplied_messages(self):
        opener = self.response({"message": {"content": "你好 / Hello"}})
        messages = [{"role": "user", "content": "你好"}]
        with patch.object(ai.request, "build_opener", return_value=opener):
            self.assertEqual(ai.chat(messages, self.settings), "你好 / Hello")
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "http://localhost:11434/api/chat")
        self.assertEqual(json.loads(req.data), {"model": "installed-model", "messages": messages, "stream": False})
        self.assertNotIn("Authorization", req.headers)

    def test_compatible_chat_uses_environment_key_and_v1_base(self):
        settings = dict(self.settings, provider="openai-compatible", endpoint="https://example.org/v1", api_key_env="TEST_CHAT_KEY")
        opener = self.response({"choices": [{"message": {"content": "Answer"}}]})
        with patch.dict(os.environ, {"TEST_CHAT_KEY": "test-secret"}), patch.object(ai.request, "build_opener", return_value=opener):
            self.assertEqual(ai.chat([{"role": "user", "content": "Hello"}], settings), "Answer")
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://example.org/v1/chat/completions")
        self.assertEqual(req.headers["Authorization"], "Bearer test-secret")

    def test_settings_store_no_key_and_use_private_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_STATE_HOME": temp, "TEST_CHAT_KEY": "secret-value"}):
            ai.save_settings(dict(self.settings, api_key_env="TEST_CHAT_KEY", api_key="never-save-me"))
            data = ai.settings_path().read_text()
            self.assertNotIn("secret-value", data)
            self.assertNotIn("never-save-me", data)
            self.assertEqual(ai.settings_path().stat().st_mode & 0o777, 0o600)
            self.assertEqual(ai.load_settings()["model"], "installed-model")

    def test_invalid_endpoint_rejected_before_network(self):
        with patch.object(ai.request, "build_opener") as opener:
            for endpoint in ("file:///etc/passwd", "https://user:password@example.org", "http://example.org", "https://example.org?key=secret", "http://localhost:invalid"):
                with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                    ai.chat([{"role": "user", "content": "hello"}], dict(self.settings, endpoint=endpoint))
            opener.assert_not_called()

    def test_missing_key_and_model_are_actionable(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "unset"):
            ai.discover_models(dict(self.settings, api_key_env="ABSENT_KEY"))
        with self.assertRaisesRegex(ValueError, "Choose a model"):
            ai.chat([{"role": "user", "content": "hello"}], ai.DEFAULTS)

    def test_malformed_credential_never_appears_in_error(self):
        for secret in ("fake-secret\n", "fake-secret\r", "fake-secret中", "fake secret"):
            with patch.dict(os.environ, {"TEST_CHAT_KEY": secret}), patch.object(ai.request, "build_opener") as opener:
                with self.assertRaisesRegex(ValueError, "invalid characters") as exc:
                    ai.discover_models(dict(self.settings, api_key_env="TEST_CHAT_KEY"))
                self.assertNotIn("fake", str(exc.exception))
                opener.assert_not_called()

    def test_provider_error_does_not_echo_sensitive_body(self):
        opener = self.response({"error": "secret prompt"})
        with patch.object(ai.request, "build_opener", return_value=opener), self.assertRaisesRegex(ValueError, "Provider returned") as exc:
            ai.chat([{"role": "user", "content": "hello"}], self.settings)
        self.assertNotIn("secret prompt", str(exc.exception))

    def test_bad_and_empty_provider_responses(self):
        for data in ({}, {"message": {"content": ""}}, {"message": {"content": None}}, []):
            with self.subTest(data=data), patch.object(ai.request, "build_opener", return_value=self.response(data)), self.assertRaises(ValueError):
                ai.chat([{"role": "user", "content": "hello"}], self.settings)

    def test_network_errors_and_redirects(self):
        for error in (URLError("unavailable"), HTTPError("https://example.org", 401, "private", {}, None)):
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.object(ai.request, "build_opener", return_value=opener), self.assertRaises(ValueError):
                ai.discover_models(self.settings)
        self.assertIsNone(ai.NoRedirect().redirect_request(None, None, 302, None, {}, "https://elsewhere.example"))

    def test_model_discovery(self):
        with patch.object(ai.request, "build_opener", return_value=self.response({"models": [{"name": "local-model"}]})):
            self.assertEqual(ai.discover_models(self.settings), ["local-model"])


if __name__ == "__main__":
    unittest.main()
