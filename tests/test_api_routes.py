"""Every HTTP route the web UI calls must answer (regression net for 500s).

These are cheap and dependency free; they caught a 500 on /api/remember and a
missing GET /api/notes.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class TestUiRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dastyar-routes-")
        cls.port = _free_port()
        env = dict(os.environ, DASTYAR_DATA=cls.tmp)
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "dastyar", "serve", "--port", str(cls.port),
             "--no-browser"],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.base = "http://127.0.0.1:%d" % cls.port
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/health", timeout=1)
                return
            except Exception:
                if cls.proc.poll() is not None:
                    raise RuntimeError("server exited early")
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def call(self, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_all_ui_routes_are_healthy(self):
        cases = [
            ("/api/health", None),
            ("/api/state", None),
            ("/api/settings", None),
            ("/api/settings", {"policy": "ask"}),
            ("/api/settings", {"base_url": "not-a-url"}),   # must be rejected politely
            ("/api/tools", None),
            ("/api/notes", None),
            ("/api/session", None),
            ("/api/sessions", None),
            ("/api/remember", {"fact": "اسم من سعید است"}),
            ("/api/remember", {}),                            # 400, never 500
            ("/api/chat", {"message": "سلام"}),
            ("/api/stop", {}),
            ("/api/confirm", {"id": "nope", "ok": True}),
            ("/api/test-connection", {}),
        ]
        for path, payload in cases:
            with self.subTest(path=path, payload=payload):
                status, text = self.call(path, payload)
                self.assertIn(status, (200, 400, 404), "%s -> %s %s" % (path, status, text))
                self.assertNotIn("Traceback", text)

    def test_static_assets_are_served(self):
        for path, needle in (
            ("/", "دستیار"),
            ("/app.js", "handleEvent"),
            ("/styles.css", "font-face"),
            ("/fonts/vazirmatn-regular.woff2", None),
            ("/logo.svg", "<svg"),
        ):
            with self.subTest(path=path):
                with urllib.request.urlopen(self.base + path, timeout=10) as r:
                    self.assertEqual(r.status, 200)
                    body = r.read()
                self.assertGreater(len(body), 100)
                if needle:
                    self.assertIn(needle, body.decode("utf-8", "replace"))

    def test_unknown_route_is_json_404(self):
        status, text = self.call("/api/definitely-not-a-route")
        self.assertEqual(status, 404)
        self.assertIn("error", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
