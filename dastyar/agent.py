"""The agent loop: think → call tools → observe → answer.

Pure Python, provider-agnostic (OpenAI-compatible tool calling), with:
  * streaming text
  * multi-step tool use with a safety cap
  * human-in-the-loop confirmation for dangerous tools
  * vision (screen / image attachments)
  * long-term memory + auto skills injected into the system prompt
  * session persistence
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import __version__
from .config import IS_MAC, IS_LINUX, IS_WINDOWS, data_dir, os_label
from .llm import LLMClient, LLMError
from .skills import match_skills
from .tools import ToolRegistry
from .tools.memory import memory_prompt
from .tools.vision import image_to_data_url


class Confirmation:
    """A blocking yes/no request shown in the UI."""

    def __init__(self, payload: Dict[str, Any]):
        self.id = uuid.uuid4().hex[:10]
        self.payload = payload
        self.event = threading.Event()
        self.approved = False

    def resolve(self, approved: bool) -> None:
        self.approved = bool(approved)
        self.event.set()

    def wait(self, timeout: float = 300) -> bool:
        self.event.wait(timeout)
        return self.approved


class Agent:
    def __init__(self, settings, emit: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.settings = settings
        self._emit_cb = emit or (lambda e: None)
        self._event_sink: Optional[List[Dict[str, Any]]] = None
        self.pending: Dict[str, Confirmation] = {}
        self.registry = ToolRegistry(
            settings, policy_confirm=self._ask_user, emit=self._emit
        )
        self.client = LLMClient(settings)
        self.messages: List[Dict[str, Any]] = []
        self.session_id = time.strftime("%Y%m%d-%H%M%S")
        self._lock = threading.RLock()
        self.attachments_shown: List[Dict[str, Any]] = []
        self._current_confirmation: Optional[Confirmation] = None
        self.cancelled = threading.Event()
        self._turn_finished = threading.Event()
        self._turn_finished.set()

    # ------------------------------------------------------------------ #
    # plumbing
    # ------------------------------------------------------------------ #
    def _emit(self, event: Dict[str, Any]) -> None:
        """Fan out an event to the current turn sink and to the app bus."""
        sink = self._event_sink
        if sink is not None:
            sink.append(event)
        try:
            self._emit_cb(event)
        except Exception:
            pass

    def _ask_user(self, payload: Dict[str, Any]) -> bool:
        conf = Confirmation(payload)
        self.pending[conf.id] = conf
        self._current_confirmation = conf
        self._emit({"type": "confirm_request", "id": conf.id, **payload})
        ok = conf.wait(timeout=600)
        self.pending.pop(conf.id, None)
        self._current_confirmation = None
        self._emit({"type": "confirm_resolved", "id": conf.id, "approved": ok})
        return ok

    def cancel(self) -> None:
        """Ask the running turn to stop after the current step."""
        if self._turn_finished.is_set():
            return  # nothing is running: don't poison the next message
        self.cancelled.set()
        for conf in list(self.pending.values()):
            conf.resolve(False)

    def resolve_confirmation(self, conf_id: str, approved: bool) -> bool:
        conf = self.pending.get(conf_id)
        if not conf:
            return False
        conf.resolve(approved)
        return True

    # ------------------------------------------------------------------ #
    # prompt
    # ------------------------------------------------------------------ #
    def system_prompt(self) -> str:
        parts = [self.settings.system_prompt]
        parts.append(
            "\n---\nاطلاعات محیط اجرا:\n"
            "سیستم‌عامل: %s\n"
            "پوشه‌ی خانه: %s\n"
            "دستیار: نسخه %s\n"
            "سیاست دسترسی ابزارها: %s\n"
            % (
                os_label(),
                Path.home(),
                __version__,
                {"ask": "قبل از کارهای خطرناک از کاربر تأیید بگیر",
                 "auto": "خودکار (بدون پرسیدن)", "readonly": "فقط خواندنی"}.get(
                    str(self.settings.get("policy")), "ask"),
            )
        )
        allowed = "، ".join(str(p) for p in self.settings.allowed_paths)
        if self.settings.get("allow_all_paths"):
            parts.append("دسترسی به فایل: همه‌جای سیستم آزاد است.")
        else:
            parts.append("مسیرهای مجاز فایل: %s" % (allowed or "—"))
        name = self.settings.get("user_name")
        if name:
            parts.append("نام کاربر: %s" % name)
        mem = memory_prompt()
        if mem:
            parts.append("\n" + mem)
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # conversation
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        with self._lock:
            self.messages = []
            self.session_id = time.strftime("%Y%m%d-%H%M%S")

    def history(self) -> List[Dict[str, Any]]:
        out = []
        for m in self.messages:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                out.append({"role": m["role"], "content": m["content"], "ts": m.get("ts")})
        return out

    def save_session(self) -> None:
        if not self.messages:
            return
        path = data_dir() / "sessions" / ("%s.json" % self.session_id)
        try:
            path.write_text(
                json.dumps(
                    {"id": self.session_id, "messages": self.messages,
                     "saved": time.time(), "model": self.settings.get("model")},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # main loop
    # ------------------------------------------------------------------ #
    def run(self, user_text: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Iterator[Dict[str, Any]]:
        """Generator of UI events for one user turn."""
        self.cancelled.clear()  # every new turn starts fresh
        self._turn_finished.clear()
        events: List[Dict[str, Any]] = []
        done = threading.Event()
        fail: List[BaseException] = []
        self._event_sink = events

        def worker() -> None:
            try:
                for ev in self._run_inner(user_text, attachments or []):
                    events.append(ev)
            except BaseException as exc:  # pragma: no cover
                fail.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        cursor = 0
        while True:
            while cursor < len(events):
                yield events[cursor]
                cursor += 1
            if done.is_set() and cursor >= len(events):
                break
            time.sleep(0.02)
        self._event_sink = None
        if fail:
            yield {"type": "error", "message": "%s: %s" % (type(fail[0]).__name__, fail[0])}
            yield {"type": "done"}
        thread.join(timeout=2)

    def _run_inner(self, user_text: str, attachments: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        user_text = (user_text or "").strip()
        if not user_text and not attachments:
            yield {"type": "error", "message": "پیام خالی است."}
            yield {"type": "done"}
            return

        # --- build the user message (text + optional images) -------------
        message: Dict[str, Any] = {"role": "user", "content": user_text, "ts": time.time()}
        if attachments and self.settings.get("vision", True):
            content: List[Dict[str, Any]] = []
            if user_text:
                content.append({"type": "text", "text": user_text})
            for att in attachments:
                path = att.get("path") if isinstance(att, dict) else str(att)
                if path and Path(path).exists():
                    try:
                        content.append({"type": "image_url",
                                        "image_url": {"url": image_to_data_url(path)}})
                    except Exception:
                        continue
            if content:
                message["content"] = content
        self.messages.append(message)
        yield {"type": "user_message", "content": user_text, "attachments": attachments}

        # --- optional skills ---------------------------------------------
        skills = match_skills(user_text) if self.settings.get("auto_skills", True) else []
        system_text = self.system_prompt()
        if skills:
            system_text += "\n\n" + "\n\n".join(s["prompt"] for s in skills)
            yield {"type": "skills", "items": [{"name": s["name"], "description": s["description"]}
                                               for s in skills]}

        max_steps = int(self.settings.get("max_steps") or 24)
        final_text = ""
        for step in range(max_steps):
            if self.cancelled.is_set():
                self._turn_finished.set()
                yield {"type": "stopped"}
                yield {"type": "done", "session": self.session_id}
                return
            messages = [{"role": "system", "content": system_text}] + [
                _sanitize(m) for m in self.messages
            ]
            tools = self.registry.schemas()
            streamed: List[str] = []

            def on_delta(piece: str) -> None:
                streamed.append(piece)
                yield_queue.append({"type": "assistant_delta", "text": piece})

            yield_queue: List[Dict[str, Any]] = []
            # NOTE: generator yields can't happen inside the callback, so we
            # run the LLM call in a helper thread and drain the queue.
            result_box: List[Dict[str, Any]] = []
            error_box: List[BaseException] = []

            def call() -> None:
                try:
                    res = self.client.chat(messages, tools=tools, on_delta=on_delta)
                    result_box.append(res)
                except BaseException as exc:
                    error_box.append(exc)

            t = threading.Thread(target=call, daemon=True)
            t.start()
            while t.is_alive() or yield_queue:
                while yield_queue:
                    yield yield_queue.pop(0)
                if t.is_alive():
                    time.sleep(0.02)
            t.join()
            if error_box:
                err = error_box[0]
                message_text = str(err)
                if isinstance(err, LLMError):
                    message_text = str(err)
                    if err.status == 401:
                        self.settings.set("provider", "demo", save=True)
                        message_text += "\n\n(به حالت نمایشی سوییچ کردم تا بدون کلید هم کار کنی.)"
                self._turn_finished.set()
                yield {"type": "error", "message": message_text}
                yield {"type": "done"}
                return

            if self.cancelled.is_set():
                self._turn_finished.set()
                yield {"type": "stopped"}
                yield {"type": "done", "session": self.session_id}
                return

            reply = result_box[0] if result_box else {"content": "", "tool_calls": []}
            content = reply.get("content") or ""
            tool_calls = reply.get("tool_calls") or []
            final_text = content

            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content,
                                             "ts": time.time()}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)

            if tool_calls:
                yield {"type": "assistant_message", "content": content, "partial": True}
                for call_info in tool_calls:
                    name = (call_info.get("function") or {}).get("name") or ""
                    raw_args = (call_info.get("function") or {}).get("arguments") or "{}"
                    call_id = call_info.get("id") or uuid.uuid4().hex[:8]
                    if self.cancelled.is_set():
                        break
                    result = self.registry.execute(name, raw_args)
                    out = result.get("output") or ""
                    err = result.get("error") or ""
                    attach = result.get("attach") or {}
                    model_text = out if result.get("ok") else ("خطا: " + err + ("\n" + out if out else ""))
                    if attach.get("for_model") and attach.get("path"):
                        try:
                            self.messages.append({
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "نتیجه‌ی ابزار %s: تصویر پیوست شد." % name},
                                    {"type": "image_url",
                                     "image_url": {"url": image_to_data_url(attach["path"])}},
                                ],
                                "ts": time.time(),
                            })
                        except Exception:
                            pass
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": model_text[:20000] or "(بدون خروجی)",
                    })
                    yield {
                        "type": "tool_result",
                        "tool": name,
                        "ok": bool(result.get("ok")),
                        "output": out[:4000],
                        "error": err[:1000],
                        "attach": attach if attach and not attach.get("for_model") else None,
                    }
                continue  # next step: send tool results back to the model

            # no tool calls -> final answer
            yield {"type": "assistant_message", "content": content, "partial": False}
            break
        else:
            yield {"type": "warning",
                   "message": "به سقف %d مرحله رسیدم؛ اگر کار نیمه‌کاره است دوباره بگو." % max_steps}
            yield {"type": "assistant_message", "content": final_text, "partial": False}

        # speak the answer if enabled
        if final_text and self.settings.get("tts_enabled") and self.settings.get("tts_auto_speak"):
            try:
                from . import voice

                voice.speak(_strip_markdown(final_text)[:900],
                            engine=self.settings.get("tts_engine", "auto"),
                            voice=self.settings.get("tts_voice", ""))
            except Exception:
                pass

        self.save_session()
        self._turn_finished.set()
        yield {"type": "done", "session": self.session_id}


def _sanitize(message: Dict[str, Any]) -> Dict[str, Any]:
    """Strip local-only keys before sending to the API."""
    out = {k: v for k, v in message.items() if k in ("role", "content", "tool_calls", "tool_call_id", "name")}
    if out.get("role") == "assistant" and not out.get("tool_calls"):
        out.pop("tool_calls", None)
    if out.get("content") is None:
        out["content"] = ""
    return out


def _strip_markdown(text: str) -> str:
    import re

    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"[*_#>~]", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()
