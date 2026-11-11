"""Local web server: REST + SSE API and the single-page UI (stdlib only)."""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import secrets
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .agent import Agent
from .config import (
    IS_WINDOWS,
    PROVIDERS,
    Settings,
    data_dir,
    ensure_data_dir,
    home,
    os_label,
)
from .secret import masked, protect
from .skills import all_skills
from .tools import notes as notes_tool
from .tools.memory import load_memory
from .tools.schedule import start_reminder_thread
from .utils import human_size, run, truncate

def _static_dir() -> Path:
    """Locate the bundled web UI for source, onedir and onefile builds."""
    here = Path(__file__).resolve().parent / "web"
    if here.is_dir():
        return here
    for base in (getattr(sys, "_MEIPASS", ""), str(Path(sys.executable).resolve().parent),
                 str(Path(sys.executable).resolve().parent / "_internal")):
        if not base:
            continue
        cand = Path(base) / "dastyar" / "web"
        if cand.is_dir():
            return cand
    return here


STATIC = _static_dir()
MAX_UPLOAD = 25 * 1024 * 1024


class App:
    """Holds the single Agent instance and the event bus for the UI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.subscribers: List["queue.Queue[Dict[str, Any]]"] = []
        self.lock = threading.Lock()
        self._busy = False
        self.agent = Agent(settings, emit=None)  # events flow through /api/chat
        self.agent_lock = threading.Lock()
        self.started = time.time()
        self._last_activity = time.time()

    # -- event bus ----------------------------------------------------
    def publish(self, event: Dict[str, Any]) -> None:
        event.setdefault("ts", time.time())
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass
        self._last_activity = time.time()

    def subscribe(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=2000)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    @property
    def last_activity(self) -> float:
        return self._last_activity


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Dastyar/%s" % __version__
        protocol_version = "HTTP/1.1"

        # ---- helpers ------------------------------------------------
        def log_message(self, fmt: str, *args: Any) -> None:
            if os.environ.get("DASTYAR_DEBUG"):
                try:
                    print("[http] " + (fmt % args))
                except Exception:
                    pass

        # ---- LAN access token --------------------------------------
        def _wanted_token(self) -> str:
            return os.environ.get("DASTYAR_TOKEN") or ""

        def _given_token(self) -> str:
            header = self.headers.get("X-Dastyar-Token") or ""
            if not header:
                auth = self.headers.get("Authorization") or ""
                if auth.lower().startswith("bearer "):
                    header = auth[7:]
            if not header:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                header = (qs.get("token") or [""])[0]
            if not header:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    name, _, val = part.strip().partition("=")
                    if name == "dastyar_token":
                        header = val
            return header

        def _auth_ok(self) -> bool:
            """True when the request may proceed.

            A token is only enforced when the server is reachable from the
            network (host != loopback); otherwise anything on this PC — i.e.
            you — is implicitly trusted, exactly like every other desktop app.
            """
            want = self._wanted_token()
            if not want:
                return True
            if secrets.compare_digest(self._given_token(), want):
                return True
            return False

        def _reject_token(self) -> None:
            # asks the browser for the token once, then keeps it in a cookie
            body = ("<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
                    "<title>دستیار — نیاز به کد دسترسی</title>"
                    "<body style='font-family:system-ui;background:#0f1420;color:#e6edf7;"
                    "display:grid;place-items:center;height:100vh;margin:0'>"
                    "<form method='get' style='text-align:center'>"
                    "<h2>🔒 کد دسترسی</h2>"
                    "<p style='color:#8b98ad'>این نمونه روی شبکه باز شده است.</p>"
                    "<input name='token' autofocus style='padding:10px 14px;border-radius:10px;"
                    "border:1px solid #2a3550;background:#161d2b;color:#fff;min-width:260px'>"
                    "<button style='padding:10px 18px;margin-inline-start:8px;border-radius:10px;"
                    "border:0;background:#4c8dff;color:#fff;cursor:pointer'>ورود</button>"
                    "</form></body></html>").encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

        def send_json(self, data: Any, status: int = 200) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(raw)

        def send_text(self, text: str, status: int = 200, ctype: str = "text/plain; charset=utf-8") -> None:
            raw = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if path.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            if path.suffix in (".html", ".css", ".svg"):
                ctype += "; charset=utf-8"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _serve_local_file(self, encoded: str) -> None:
            """Serve a local file to the UI (images/previews) — LAN only by design."""
            try:
                # the request arrives with a leading slash that is not part of the
                # real path on Windows (C:\...) or POSIX (/home/...)
                raw = urllib.parse.unquote(encoded)
                candidate = Path(raw) if raw.startswith("/") is False else Path("/" + raw)
                if IS_WINDOWS and len(raw) > 1 and raw[1] == ":":
                    candidate = Path(raw)
                if not candidate.exists():
                    alt = Path("/" + raw)
                    candidate = alt if alt.exists() else candidate
                self.send_file(candidate)
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)

        def read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        # ---- routing ------------------------------------------------
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if self._wanted_token() and not self._auth_ok():
                # the page itself may load (it shows the token form); anything
                # that touches data or settings requires the cookie
                if path in ("/", "/index.html"):
                    return self.send_file(STATIC / "index.html")
                return self._reject_token()
            if query.get("token") and self._wanted_token() and self._auth_ok():
                # remember it, then drop it from the address bar
                target = parsed._replace(query="").geturl() or "/"
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Set-Cookie", "dastyar_token=%s; Path=/; SameSite=Lax; HttpOnly"
                                 % query["token"][0])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                if path == "/api/health":
                    return self.send_json({
                        "ok": True, "version": __version__, "os": os_label(),
                        "uptime": int(time.time() - app.started),
                        "provider": app.settings.get("provider"),
                        "model": app.settings.get("model"),
                    })
                if path == "/api/events":
                    return self.stream_events()
                if path == "/api/state":
                    return self.send_json({
                        "data_dir": str(data_dir()),
                        "settings": app.settings.public_dict(),
                        "history": app.agent.history(),
                        "notes": notes_tool.notes_snapshot(),
                        "memory": load_memory()[-30:],
                        "skills": [{"name": s["name"], "description": s.get("description", "")}
                                   for s in all_skills()],
                        "version": __version__,
                    })
                if path == "/api/settings":
                    return self.send_json({"settings": app.settings.public_dict(),
                                           "providers": PROVIDERS})
                if path == "/api/tools":
                    return self.send_json({"tools": app.agent.registry.list_for_ui()})
                if path == "/api/sessions":
                    items = []
                    for p in sorted((data_dir() / "sessions").glob("*.json"), reverse=True)[:30]:
                        try:
                            d = json.loads(p.read_text(encoding="utf-8"))
                            items.append({"id": d.get("id") or p.stem, "saved": d.get("saved"),
                                          "model": d.get("model"),
                                          "messages": len(d.get("messages") or [])})
                        except Exception:
                            continue
                    return self.send_json({"sessions": items})
                if path == "/api/session":
                    sid = (query.get("id") or [""])[0]
                    p = (data_dir() / "sessions" / (sid + ".json"))
                    if not p.exists():
                        return self.send_json({"error": "not found"}, 404)
                    return self.send_json(json.loads(p.read_text(encoding="utf-8")))
                if path == "/api/voice":
                    from .voice import available_engines

                    return self.send_json(available_engines())
                if path == "/api/download":
                    target = (query.get("path") or [""])[0]
                    if not target:
                        return self.send_json({"error": "path required"}, 400)
                    p = Path(os.path.expanduser(target)).resolve()
                    allowed_root = data_dir().resolve()
                    if not str(p).startswith(str(allowed_root)):
                        return self.send_json({"error": "forbidden"}, 403)
                    return self.send_file(p)
                if path.startswith("/file/"):
                    return self._serve_local_file(path[6:])
                if path == "/" or path == "":
                    return self.send_file(STATIC / "index.html")
                # static assets
                rel = path.lstrip("/")
                if ".." not in rel:
                    candidate = (STATIC / rel)
                    if candidate.exists():
                        return self.send_file(candidate)
                return self.send_json({"error": "not found", "path": path}, 404)
            except BrokenPipeError:
                pass
            except Exception as exc:  # pragma: no cover
                try:
                    self.send_json({"error": str(exc)}, 500)
                except Exception:
                    pass

        def do_POST(self) -> None:  # noqa: N802
            if self._wanted_token() and not self._auth_ok():
                return self.send_json({"ok": False, "error": "کد دسترسی نامعتبر است"}, 401)
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            body = self.read_json()
            try:
                if path == "/api/chat":
                    return self.chat(body)
                if path == "/api/stop":
                    app.agent.cancel()
                    app.publish({"type": "stopped"})
                    return self.send_json({"ok": True})
                if path == "/api/settings":
                    return self.update_settings(body)
                if path == "/api/test-connection":
                    return self.test_connection()
                if path == "/api/confirm":
                    cid = body.get("id", "")
                    ok = app.agent.resolve_confirmation(cid, bool(body.get("approved")))
                    return self.send_json({"ok": ok})
                if path == "/api/reset":
                    app.agent.reset()
                    app.publish({"type": "reset"})
                    return self.send_json({"ok": True})
                if path == "/api/notes":
                    action = body.get("action")
                    if action == "add":
                        notes_tool.write_note(body.get("text", ""), body.get("title") or "یادداشت")
                    elif action == "delete":
                        notes_tool.delete_note(body.get("query", ""))
                    elif action == "todo":
                        notes_tool.add_todo(body.get("text", ""))
                    elif action == "complete":
                        notes_tool.complete_todo(body.get("query", ""))
                    app.publish({"type": "notes_updated"})
                    return self.send_json(notes_tool.notes_snapshot())
                if path == "/api/remember":
                    from .tools.memory import remember

                    out = remember(body.get("fact", ""), body.get("tag", "general"))
                    return self.send_json({"ok": True, "result": out})
                if path == "/api/tts":
                    from . import voice as voice_mod

                    text = body.get("text", "")
                    if not text:
                        return self.send_json({"ok": False, "error": "empty"}, 400)
                    res = voice_mod.speak(text, voice=app.settings.get("tts_voice", ""),
                                          engine=app.settings.get("tts_engine", "auto"))
                    return self.send_json(res)
                if path == "/api/stt":
                    from . import voice as voice_mod

                    seconds = float(body.get("seconds") or 5)
                    try:
                        wav = voice_mod.record_microphone(seconds)
                        res = voice_mod.transcribe(
                            wav,
                            api_key=app.settings.api_key,
                            base_url=app.settings.base_url,
                            model=app.settings.get("stt_model") or "whisper-1",
                        )
                        return self.send_json(res)
                    except Exception as exc:
                        return self.send_json({"ok": False, "error": str(exc)})
                if path == "/api/open":
                    from .utils import os_open

                    target = body.get("path", "")
                    ok = os_open(target) if target else False
                    return self.send_json({"ok": bool(ok)})
                if path == "/api/upload":
                    return self.upload()
                if path == "/api/shutdown":
                    self.send_json({"ok": True})
                    threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
                    return
                return self.send_json({"error": "not found"}, 404)
            except BrokenPipeError:
                pass
            except Exception as exc:  # pragma: no cover
                try:
                    self.send_json({"error": str(exc)}, 500)
                except Exception:
                    pass

        def upload(self) -> None:
            """Accept one multipart/form-data file (image for vision)."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            if length <= 0:
                return self.send_json({"error": "فایل خالی است"}, 400)
            if length > MAX_UPLOAD:
                return self.send_json({"error": "فایل بزرگ‌تر از ۲۵ مگابایت است"}, 413)
            ctype = self.headers.get("Content-Type") or ""
            boundary = ""
            for part in ctype.split(";"):
                part = part.strip()
                if part.lower().startswith("boundary="):
                    boundary = part.split("=", 1)[1].strip().strip('"')
            if not boundary:
                return self.send_json({"error": "فرمت آپلود نامعتبر"}, 400)
            raw = self.rfile.read(length)
            delim = b"--" + boundary.encode()
            chunks = raw.split(delim)
            for chunk in chunks:
                if b"\r\n\r\n" not in chunk:
                    continue
                head, body = chunk.split(b"\r\n\r\n", 1)
                if b"filename=" not in head:
                    continue
                fname = "upload"
                for piece in head.decode("utf-8", "replace").split(";"):
                    piece = piece.strip()
                    if piece.startswith("filename="):
                        fname = piece.split("=", 1)[1].strip().strip('"')
                body = body.rstrip(b"\r\n-")
                from .utils import sanitize_filename

                safe = sanitize_filename(fname or "upload.png", "upload.png")
                stamp = time.strftime("%Y%m%d-%H%M%S")
                dest = ensure_data_dir() / "downloads" / ("%s-%s" % (stamp, safe))
                dest.write_bytes(body)
                return self.send_json({"ok": True, "path": str(dest), "name": safe,
                                       "size": len(body)})
            return self.send_json({"error": "فایلی در درخواست نبود"}, 400)

        # ---- endpoints ----------------------------------------------
        def stream_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._cors()
            self.end_headers()
            q = app.subscribe()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                last_ping = time.time()
                while True:
                    try:
                        event = q.get(timeout=1.0)
                        payload = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                        self.wfile.write(payload.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        if time.time() - last_ping > 15:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            last_ping = time.time()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.unsubscribe(q)

        def chat(self, body: Dict[str, Any]) -> None:
            text = (body.get("message") or "").strip()
            attachments = body.get("attachments") or []
            if not text and not attachments:
                return self.send_json({"ok": False, "error": "پیام خالی است."}, 400)
            app.publish({"type": "thinking"})
            for event in app.agent.run(text, attachments):
                app.publish(event)
            return self.send_json({"ok": True})

        def update_settings(self, body: Dict[str, Any]) -> None:
            payload = body.get("settings") or body
            allowed_keys = {
                "provider", "model", "base_url", "temperature", "max_steps", "policy",
                "allowed_paths", "allow_all_paths", "user_name", "language", "vision",
                "tts_enabled", "tts_engine", "tts_voice", "tts_auto_speak", "stt_engine",
                "web_search", "ui", "hotkey", "system_prompt", "auto_skills", "image_model",
                "stt_model",
            }
            errors = []
            for key, value in (payload or {}).items():
                if key == "api_key":
                    if value and "•" not in str(value):
                        app.settings.set("api_key", protect(str(value)))
                    continue
                if key == "base_url":
                    value = str(value or "").strip().rstrip("/")
                    if value and not value.startswith(("http://", "https://")):
                        errors.append("آدرس سرور باید با http:// یا https:// شروع شود")
                        continue
                if key == "allowed_paths" and isinstance(value, list):
                    value = [str(p).strip() for p in value if str(p).strip()]
                    if not value:
                        errors.append("حداقل یک مسیر مجاز لازم است")
                        continue
                if key == "policy" and value not in ("ask", "auto", "readonly"):
                    errors.append("سیاست نامعتبر")
                    continue
                if key == "max_steps":
                    try:
                        value = max(2, min(80, int(value)))
                    except Exception:
                        continue
                if key in allowed_keys:
                    app.settings.set(key, value, save=False)
            app.settings.save()
            app.agent.registry.settings = app.settings
            app.agent.registry.context.settings = app.settings
            return self.send_json({"ok": True, "settings": app.settings.public_dict(),
                                   "errors": errors})

        def test_connection(self) -> None:
            from .llm import LLMClient

            res = LLMClient(app.settings).test_connection()
            return self.send_json(res)

    return Handler


def _lan_ip() -> str:
    """Best-effort local IP address (no traffic is actually sent)."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        finally:
            probe.close()
    except Exception:
        return "127.0.0.1"


def _find_free_port(host: str, start: int, tries: int = 30) -> int:
    if host in ("0.0.0.0", "::", ""):
        probe_host = ""          # any interface
    else:
        probe_host = host
    for port in range(start, start + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((probe_host, port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return start


def serve(settings: Settings, port: Optional[int] = None, host: Optional[str] = None,
          open_browser: bool = True, quiet: bool = False) -> None:
    ensure_data_dir()
    port = int(port or settings.get("ui.port") or 8577)
    host = host or settings.get("ui.host") or "127.0.0.1"
    if host in ("0.0.0.0", "::", ""):
        # exposed on the network: allow http://<ip>:<port>?token=... access
        token = os.environ.get("DASTYAR_TOKEN") or settings.get("ui.token") or ""
        if not token:
            token = secrets.token_urlsafe(18)
            settings.set("ui.token", token, save=True)
        os.environ["DASTYAR_TOKEN"] = token
    port = _find_free_port(host, port)
    app = App(settings)
    start_reminder_thread()

    # idle watchdog: quit when nobody is using the UI for a long time
    if settings.get("ui.shutdown_when_idle", False):
        def watchdog() -> None:
            while True:
                time.sleep(60)
                if not app.subscribers and time.time() - app.last_activity > 3600:
                    os._exit(0)

        threading.Thread(target=watchdog, daemon=True).start()

    handler = make_handler(app)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    local_url = "http://127.0.0.1:%d" % port
    if not quiet:
        print("\n  دستیار %s آماده است 🚀" % __version__)
        print("  ─────────────────────────────────")
        print("  آدرس:  %s" % local_url)
        if host not in ("127.0.0.1", "localhost"):
            lan_ip = _lan_ip()
            token = os.environ.get("DASTYAR_TOKEN", "")
            print("  شبکه:  http://%s:%d" % (lan_ip, port))
            if token:
                print("  کد:    %s" % token)
            print("  ⚠️  این نمونه از شبکه در دسترس است — کد بالا را با کسی شریک نشو.")
        print("  بستن:  Ctrl+C\n")
    if open_browser:
        def opener() -> None:
            time.sleep(0.8)
            from .utils import os_open

            os_open(local_url)

        threading.Thread(target=opener, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nخداحافظ! 👋")
    finally:
        httpd.server_close()
