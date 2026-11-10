"""End-to-end test: a fake OpenAI-compatible server drives the real agent loop.

This proves streaming, tool-calling, confirmation and attachments work without
any API key or internet access.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dastyar.agent import Agent  # noqa: E402
from dastyar.config import Settings  # noqa: E402


class FakeLLM:
    """Serves /v1/chat/completions and replays a scripted conversation."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests.append(body)
                step = outer.script.pop(0) if outer.script else {"text": "تمام."}
                stream = bool(body.get("stream"))
                if not stream:
                    payload = {
                        "id": "x", "object": "chat.completion",
                        "choices": [{"index": 0, "message": {
                            "role": "assistant",
                            "content": step.get("text", ""),
                            "tool_calls": step.get("tool_calls", []),
                        }, "finish_reason": "stop"}],
                    }
                    raw = json.dumps(payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                text = step.get("text", "")
                for i in range(0, len(text), 4):
                    chunk = {"choices": [{"index": 0, "delta": {"content": text[i:i + 4]}}]}
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    self.wfile.flush()
                for idx, call in enumerate(step.get("tool_calls", [])):
                    for frag_i in range(0, len(call["function"]["arguments"]), 6):
                        delta = {"tool_calls": [{
                            "index": idx, "id": call["id"] if frag_i == 0 else None,
                            "type": "function",
                            "function": {
                                "name": call["function"]["name"] if frag_i == 0 else None,
                                "arguments": call["function"]["arguments"][frag_i:frag_i + 6],
                            },
                        }]}
                        chunk = {"choices": [{"index": 0, "delta": delta}]}
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self):
        return "http://127.0.0.1:%d/v1" % self.port

    def stop(self):
        self.httpd.shutdown()


class TestAgentEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.settings = Settings(base / "cfg.json")
        self.settings.update({
            "provider": "custom",
            "model": "fake-model-1",
            "policy": "auto",
            "allowed_paths": [str(self.home)],
            "vision": True,
            "tts_enabled": False,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_streaming_tool_call_roundtrip(self):
        target = self.home / "ساخته-شده.txt"
        fake = FakeLLM([
            {"text": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "write_file",
                             "arguments": json.dumps({"path": str(target), "content": "سلام از تست"})},
            }]},
            {"text": "فایل را ساختم ✅"},
        ])
        try:
            self.settings.set("base_url", fake.base_url)
            agent = Agent(self.settings)
            events = list(agent.run("یک فایل بساز"))
        finally:
            fake.stop()

        kinds = [e["type"] for e in events]
        self.assertIn("assistant_delta", kinds)
        self.assertIn("tool_start", kinds)
        self.assertIn("tool_result", kinds)
        self.assertTrue(target.exists(), "tool should have written the file")
        self.assertEqual(target.read_text(encoding="utf-8"), "سلام از تست")
        final = [e for e in events if e["type"] == "assistant_message"][-1]
        self.assertIn("فایل را ساختم", final["content"])
        # the tool result must be sent back to the model in the 2nd request
        self.assertEqual(len(fake.requests), 2)
        second = fake.requests[1]
        roles = [m["role"] for m in second["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertIn("tool", roles)
        tool_msg = [m for m in second["messages"] if m["role"] == "tool"][0]
        self.assertIn("نوشته شد", tool_msg["content"])
        # tools were advertised to the model
        self.assertTrue(second.get("tools"))
        names = {t["function"]["name"] for t in second["tools"]}
        self.assertIn("write_file", names)

    def test_confirmation_policy_blocks_when_denied(self):
        fake = FakeLLM([
            {"text": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "delete_file",
                             "arguments": json.dumps({"path": str(self.home / "x.txt")})},
            }]},
            {"text": "باشه، حذف نکردم."},
        ])
        victim = self.home / "x.txt"
        victim.write_text("keep me", encoding="utf-8")
        self.settings.update({"policy": "ask", "base_url": fake.base_url})
        agent = Agent(self.settings)
        try:
            agent_events = agent.run("فایل را حذف کن")
            events = []
            for ev in agent_events:
                events.append(ev)
                if ev["type"] == "confirm_request":
                    threading.Thread(
                        target=lambda cid=ev["id"]: (time.sleep(0.1),
                                                     agent.resolve_confirmation(cid, False)),
                        daemon=True).start()
        finally:
            fake.stop()
        self.assertTrue(victim.exists(), "file must NOT be deleted after denial")
        result = [e for e in events if e["type"] == "tool_result"][0]
        self.assertFalse(result["ok"])
        self.assertIn("اجازه", result["error"])

    def test_vision_attachment_becomes_image_message(self):
        from dastyar.screen import _write_png

        img = self.home / "shot.png"
        _write_png(img, 2, 2, b"\xff\x00\x00" * 4, 6)
        fake = FakeLLM([{"text": "این یک تصویر قرمز است."}])
        try:
            self.settings.set("base_url", fake.base_url)
            agent = Agent(self.settings)
            list(agent.run("این چیست؟", [{"path": str(img)}]))
        finally:
            fake.stop()
        sent = fake.requests[0]["messages"][-1]
        self.assertEqual(sent["role"], "user")
        self.assertIsInstance(sent["content"], list)
        self.assertEqual(sent["content"][0]["type"], "text")
        self.assertTrue(sent["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_auth_error_switches_to_demo(self):
        self.settings.update({"base_url": "http://127.0.0.1:9/v1", "model": "x"})
        agent = Agent(self.settings)
        events = list(agent.run("سلام"))
        self.assertIn("error", [e["type"] for e in events])


if __name__ == "__main__":
    unittest.main(verbosity=2)
