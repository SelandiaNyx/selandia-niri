"""Cancel a chat request against a local delayed HTTP server; no live services."""
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import ai_backend as ai

REPLY = "local reply 本地回复"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        state = dict(self.server.state)
        length = int(self.headers.get("Content-Length", 0))
        state["requests"].append({"path": self.path, "auth": self.headers.get("Authorization"),
                                  "body": json.loads(self.rfile.read(length))})
        state["arrived"].set()
        time.sleep(state["header_delay"])
        payload = json.dumps({"message": {"content": state["reply"]}}).encode()
        self.send_response(state["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if state["body_delay"]:
            self.wfile.write(payload[:5])
            self.wfile.flush()
            state["body_started"].set()
            time.sleep(state["body_delay"])
            self.wfile.write(payload[5:])
        else:
            self.wfile.write(payload)
        self.wfile.flush()

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class CancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.server.state = {"requests": [], "arrived": threading.Event(), "body_started": threading.Event(), "reply": REPLY,
                            "status": 200, "header_delay": 0.0, "body_delay": 0.0}
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.spawned = []
        self.reset()

    def reset(self):
        self.server.state.update({"reply": REPLY, "status": 200, "header_delay": 0.0, "body_delay": 0.0})
        self.server.state["requests"].clear()
        self.server.state["arrived"].clear()
        self.server.state["body_started"].clear()

    def settings(self, **extra):
        return dict(ai.DEFAULTS, endpoint=self.endpoint, model="test-model", **extra)

    def run_thread(self, request):
        outcome = {}

        def body():
            try:
                outcome["reply"] = request.run()
            except BaseException as exc:
                outcome["error"] = exc
        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        return thread, outcome

    def spawn_spy(self):
        real = subprocess.Popen

        def spy(*args, **kwargs):
            process = real(*args, **kwargs)
            self.spawned.append({"argv": list(args[0]), "process": process})
            return process
        return patch.object(subprocess, "Popen", spy)

    @staticmethod
    def children():
        found = set()
        for task in Path("/proc/self/task").iterdir():
            try:
                found.update((task / "children").read_text().split())
            except OSError:
                pass
        return found

    def test_normal_reply_then_commit_blocks_cancel(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        thread, outcome = self.run_thread(request)
        thread.join(10)
        self.assertEqual(outcome.get("reply"), REPLY)
        calls = []
        self.assertEqual(request.commit(lambda: calls.append("saved") or "saved"), "saved")
        self.assertEqual(calls, ["saved"])
        self.assertFalse(request.cancel())  # reply already saved
        self.assertFalse(request.cancel())  # repeated cancel stays reliable

    def test_cancel_before_commit_never_runs_callback(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        thread, outcome = self.run_thread(request)
        thread.join(10)
        self.assertEqual(outcome.get("reply"), REPLY)
        self.assertTrue(request.cancel())
        with self.assertRaises(ai.Cancelled):
            request.commit(lambda: self.fail("a cancelled request must never call back"))
        self.assertFalse(request.cancel())

    def test_cancel_during_delayed_headers_and_body_reaps_worker(self):
        for key in ("header_delay", "body_delay"):
            with self.subTest(key=key):
                self.reset()
                self.server.state[key] = 2.0
                baseline = self.children()
                request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
                with self.spawn_spy():
                    thread, outcome = self.run_thread(request)
                    self.assertTrue(self.server.state["arrived"].wait(5))
                    if key == "body_delay":
                        self.assertTrue(self.server.state["body_started"].wait(5))
                    started = time.monotonic()
                    self.assertTrue(request.cancel())
                    self.assertLess(time.monotonic() - started, 0.5)  # GTK thread returns at once
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertIsInstance(outcome.get("error"), ai.Cancelled)
                    self.assertLess(time.monotonic() - started, 1.5)
                    self.assertIsNotNone(self.spawned[-1]["process"].returncode)
                    self.assertEqual(self.children(), baseline)  # nothing left to reap

    def test_immediate_cancel_sends_no_request(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        self.assertTrue(request.cancel())
        with self.spawn_spy(), self.assertRaises(ai.Cancelled):
            request.run()
        self.assertEqual(self.spawned, [])  # no worker means no network
        self.assertEqual(self.server.state["requests"], [])
        self.assertFalse(request.cancel())

    def test_new_request_after_cancel_succeeds(self):
        first = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        self.assertTrue(first.cancel())
        with self.assertRaises(ai.Cancelled):
            first.run()
        second = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        thread, outcome = self.run_thread(second)
        thread.join(10)
        self.assertEqual(outcome.get("reply"), REPLY)
        self.assertTrue(second.commit(lambda: True))

    def test_cancel_during_commit_returns_false(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        thread, outcome = self.run_thread(request)
        thread.join(10)
        self.assertEqual(outcome.get("reply"), REPLY)
        entered, release, result = threading.Event(), threading.Event(), {}

        def save():
            entered.set()
            release.wait(5)
            return "saved"

        def commit():
            try:
                result["value"] = request.commit(save)
            except BaseException as exc:
                result["error"] = exc
        committer = threading.Thread(target=commit, daemon=True)
        committer.start()
        self.assertTrue(entered.wait(5))
        self.assertFalse(request.cancel())  # commit started: the reply is safe
        release.set()
        committer.join(5)
        self.assertEqual(result.get("value"), "saved")

    def test_commit_and_cancel_race_has_one_winner(self):
        for _ in range(20):
            request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
            thread, outcome = self.run_thread(request)
            thread.join(10)
            self.assertEqual(outcome.get("reply"), REPLY)
            calls, results, gate = [], [], threading.Barrier(3)

            def commit():
                gate.wait()
                try:
                    request.commit(lambda: calls.append(1))
                except ai.Cancelled:
                    results.append("cancelled")

            def cancel():
                gate.wait()
                results.append(request.cancel())

            racers = [threading.Thread(target=commit, daemon=True), threading.Thread(target=cancel, daemon=True)]
            for racer in racers:
                racer.start()
            gate.wait()
            for racer in racers:
                racer.join(5)
            if True in results:
                self.assertEqual(calls, [])       # cancel won: no reply saved
            else:
                self.assertEqual(calls, [1])      # commit won: exactly one save

    def test_total_deadline_stops_slow_server(self):
        self.server.state["header_delay"] = 5.0
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        with patch.object(ai, "CHAT_REQUEST_TIMEOUT", 0.4), self.spawn_spy():
            thread, outcome = self.run_thread(request)
            thread.join(5)
        self.assertEqual(str(outcome.get("error")), ai.TIMEOUT_ERROR)
        self.assertIsNotNone(self.spawned[-1]["process"].returncode)

    def test_server_error_is_clean_and_safe(self):
        self.server.state["status"] = 500
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())
        with self.spawn_spy():
            thread, outcome = self.run_thread(request)
            thread.join(10)
        error = outcome.get("error")
        self.assertIsInstance(error, ValueError)
        self.assertNotIn("Traceback", str(error))
        self.assertFalse(request.cancel())
        with self.assertRaises(RuntimeError):
            request.commit(lambda: self.fail("a failed request must never commit"))
        self.assertIsNotNone(self.spawned[-1]["process"].returncode)

    def test_key_stays_in_the_environment(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}],
                                 self.settings(api_key_env="CANCEL_TEST_KEY"))
        with patch.dict(os.environ, {"CANCEL_TEST_KEY": "cancel-secret"}), self.spawn_spy():
            thread, outcome = self.run_thread(request)
            thread.join(10)
        self.assertEqual(outcome.get("reply"), REPLY)
        self.assertEqual(self.server.state["requests"][0]["auth"], "Bearer cancel-secret")
        self.assertNotIn("cancel-secret", " ".join(" ".join(entry["argv"]) for entry in self.spawned))
        self.assertNotIn("cancel-secret", json.dumps(request.settings))

    def test_large_history_write_is_cancellable_and_has_total_deadline(self):
        real_popen = subprocess.Popen
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                spawned = []
                ready = threading.Event()

                def stalled_worker(*args, **kwargs):
                    process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
                    spawned.append(process)
                    ready.set()
                    return process

                request = ai.ChatRequest([{"role": "user", "content": "x" * (2 * 1024 * 1024)}], self.settings())
                with patch.object(ai, "CHAT_REQUEST_TIMEOUT", 0.4), patch.object(ai.subprocess, "Popen", side_effect=stalled_worker):
                    try:
                        thread, outcome = self.run_thread(request)
                        self.assertTrue(ready.wait(3))
                        if cancel:
                            self.assertTrue(request.cancel())
                        thread.join(3)
                        self.assertFalse(thread.is_alive())
                        if cancel:
                            self.assertIsInstance(outcome.get("error"), ai.Cancelled)
                        else:
                            self.assertEqual(str(outcome.get("error")), ai.TIMEOUT_ERROR)
                        self.assertIsNotNone(spawned[0].returncode)
                    finally:
                        for process in spawned:
                            if process.poll() is None:
                                process.kill()
                            process.wait(timeout=3)

    def test_cancellation_wins_over_a_simultaneous_transport_failure(self):
        request = ai.ChatRequest([{"role": "user", "content": "hi"}], self.settings())

        def failure():
            self.assertTrue(request.cancel())
            raise ValueError("Transport just disconnected")

        with patch.object(request, "_run_worker", side_effect=failure), self.assertRaises(ai.Cancelled):
            request.run()
        with self.assertRaises(ai.Cancelled):
            request.commit(lambda: self.fail("Cancelled failure must never save"))

    def test_request_snapshots_messages_and_settings(self):
        messages, settings = [{"role": "user", "content": "original"}], self.settings()
        request = ai.ChatRequest(messages, settings)
        messages[0]["content"] = "edited"
        settings["model"] = "edited"
        self.assertEqual(request.messages[0]["content"], "original")
        self.assertEqual(request.settings["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
