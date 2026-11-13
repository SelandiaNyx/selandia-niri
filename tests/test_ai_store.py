"""AI profiles, history isolation and interrupted atomic writes, using /tmp only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
import ai_backend
import ai_store as store


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-ai-store-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict(os.environ, XDG_STATE_HOME=str(self.root))
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def turn(self, text="Hello", response="Answer"):
        value = store.load()
        conversation = store.current_chat(value)
        return store.append_turn(value["active_profile"], conversation["id"] if conversation else None,
                                 conversation["settings"] if conversation else store.profile(value)["settings"],
                                 conversation["messages"] if conversation else [], text, response)

    def test_five_connections_coexist_and_opening_does_not_save_or_network(self):
        with patch.object(ai_backend, "_request", side_effect=AssertionError("Network prohibited")):
            self.assertEqual({p["id"] for p in store.load()["profiles"]}, {"ollama", "relay", "google", "deepseek", "openai"})
        self.assertFalse(store.path().exists())

    def test_legacy_settings_migrate_without_modifying_the_original(self):
        settings = dict(ai_backend.DEFAULTS, provider="openai-compatible", endpoint="https://relay.example/v1", model="my-model", api_key_env="MY_KEY")
        ai_backend.save_settings(settings)
        before = ai_backend.settings_path().read_bytes()
        value = store.select_profile("imported")
        self.assertEqual(store.profile(value)["settings"], settings)
        self.assertEqual(ai_backend.load_settings(), settings)
        self.assertEqual(ai_backend.settings_path().read_bytes(), before)

    def test_completed_turn_persists_and_profiles_do_not_share_messages(self):
        first = self.turn("private-local")
        store.select_profile("google")
        second = self.turn("private-google")
        self.assertEqual(len(second["conversations"]), 2)
        value = store.select_profile("ollama")
        self.assertEqual(store.current_chat(value)["messages"][0]["content"], "private-local")
        self.assertEqual(store.path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(first["conversations"]), 1)

    def test_editing_connection_preserves_old_history_and_its_endpoint(self):
        old = store.current_chat(self.turn())
        settings = dict(ai_backend.DEFAULTS, endpoint="http://localhost:12345", model="another-model")
        value = store.save_profile("ollama", "My local server", settings)
        self.assertIsNone(store.current_chat(value))
        value = store.select_chat(old["id"])
        self.assertEqual(store.current_chat(value)["settings"], old["settings"])
        self.assertEqual(store.profile(value)["settings"], settings)

    def test_new_switch_delete_only_affect_selected_conversation(self):
        old = store.current_chat(self.turn())
        store.new_chat()
        new = store.current_chat(self.turn("Second"))
        store.select_chat(old["id"])
        value = store.delete_chat()
        self.assertEqual([c["id"] for c in value["conversations"]], [new["id"]])

    def test_key_values_are_never_serialized_and_extra_secret_fields_rejected(self):
        with patch.dict(os.environ, GEMINI_API_KEY="test-secret-never-serialize"):
            store.select_profile("google")
        self.assertNotIn("test-secret", store.path().read_text())
        with self.assertRaises(ValueError):
            store.save_profile("google", "Google", dict(ai_backend.DEFAULTS, api_key="secret"))

    def test_corrupt_workspace_preserved_and_cannot_be_overwritten(self):
        store.select_profile("google")
        store.path().write_text("corrupt original")
        with self.assertRaises(ValueError):
            store.add_profile()
        self.assertEqual(store.path().read_text(), "corrupt original")

    def test_failed_replace_preserves_previous_workspace(self):
        self.turn()
        before = store.path().read_bytes()
        with patch.object(store.os, "replace", side_effect=OSError("simulated disk error")), self.assertRaises(OSError):
            store.add_profile()
        self.assertEqual(store.path().read_bytes(), before)

    def test_killed_writer_preserves_committed_history_and_releases_lock(self):
        self.turn()
        before = store.path().read_bytes()
        marker = self.root / "ready"
        program = '''import os,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1]); import ai_store
def interrupted(source,target):
 Path(sys.argv[2]).write_text("ready")
 while True: time.sleep(.1)
ai_store.os.replace=interrupted
ai_store.add_profile()
'''
        child = subprocess.Popen([sys.executable, "-B", "-c", program, str(ROOT / "niri/shell"), str(marker)], env=dict(os.environ))
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        import time
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(marker.exists())
        child.kill()
        child.wait(timeout=3)
        self.assertEqual(store.path().read_bytes(), before)
        self.assertEqual(len(store.add_profile()["profiles"]), 6)

    def test_concurrent_writes_keep_both_new_profiles(self):
        threads = [threading.Thread(target=store.add_profile) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(len(store.load()["profiles"]), 7)

    def test_stale_turn_refused_without_overwriting_new_history(self):
        first = self.turn()
        conversation = store.current_chat(first)
        before = store.path().read_bytes()
        with self.assertRaises(ValueError):
            store.append_turn("ollama", conversation["id"], conversation["settings"], [], "Stale", "Stale")
        self.assertEqual(store.path().read_bytes(), before)

    def test_all_five_profiles_chat_through_real_loopback_http_and_persist_separately(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), body))
                response = ({"message": {"content": "local answer"}} if self.path.endswith("/api/chat") else
                            {"choices": [{"message": {"content": "remote-format answer"}}]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, TEST_AI_KEY="private-loopback-key"):
                for identifier, *_ in store.TEMPLATES:
                    value = store.select_profile(identifier)
                    settings = dict(store.profile(value)["settings"], endpoint=f"http://127.0.0.1:{server.server_port}/{identifier}",
                                    model="fixture-model", api_key_env="TEST_AI_KEY" if identifier != "ollama" else "")
                    store.save_profile(identifier, identifier, settings)
                    prompt = "Only " + identifier
                    response = ai_backend.chat([{"role": "user", "content": prompt}], settings)
                    store.append_turn(identifier, None, settings, [], prompt, response)
            self.assertEqual(len(store.load()["conversations"]), 5)
            for route, authorization, body in requests:
                identifier = route.split("/")[1]
                self.assertEqual(body["messages"], [{"role": "user", "content": "Only " + identifier}])
                self.assertEqual(authorization, None if identifier == "ollama" else "Bearer private-loopback-key")
            self.assertNotIn("private-loopback-key", store.path().read_text())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
