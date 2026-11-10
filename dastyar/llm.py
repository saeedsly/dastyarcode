"""LLM client — any OpenAI-compatible endpoint, pure standard library.

Works with OpenAI, OpenRouter, Groq, DeepSeek, Gemini (OpenAI compat), Mistral,
Ollama, LM Studio and any custom base URL.  Includes streaming (SSE), tool
calling, retries and a fully offline demo mode.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import __version__

USER_AGENT = "Dastyar/%s (+https://github.com/saeedsly/dastyarcode)" % __version__


class LLMError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _friendly_http_error(status: int, body: str, provider: str) -> str:
    snippet = (body or "").strip()
    try:
        err = json.loads(snippet)
        msg = (
            (err.get("error") or {}).get("message")
            if isinstance(err.get("error"), dict)
            else err.get("error") or err.get("message")
        )
        if msg:
            snippet = str(msg)
    except Exception:
        pass
    snippet = snippet[:400]
    if status == 401:
        return "کلید API نامعتبر است یا منقضی شده (401). کلید را در تنظیمات بررسی کن. %s" % snippet
    if status == 402:
        return "اعتبار حساب کافی نیست (402). %s" % snippet
    if status == 403:
        return "دسترسی رد شد (403). شاید کلید اجازه‌ی این مدل را ندارد. %s" % snippet
    if status == 404:
        return "آدرس یا نام مدل پیدا نشد (404). base_url و model را بررسی کن. %s" % snippet
    if status == 429:
        return "درخواست‌ها زیاد شده یا سهمیه تمام شده (429). کمی صبر کن. %s" % snippet
    if status in (500, 502, 503, 504):
        return "سرور %s فعلاً مشکل دارد (%s). دوباره تلاش می‌کنم. %s" % (provider, status, snippet)
    return "خطای HTTP %s از %s: %s" % (status, provider, snippet)


class LLMClient:
    """Thin, dependency-free OpenAI-compatible client with tool calling."""

    def __init__(self, settings, timeout: int = 120):
        self.settings = settings
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # request plumbing
    # ------------------------------------------------------------------ #
    def _endpoint(self, path: str = "/chat/completions") -> str:
        base = self.settings.base_url
        if not base:
            raise LLMError("آدرس سرور (base_url) تنظیم نشده است.")
        return base + path

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        key = self.settings.api_key
        if key:
            headers["Authorization"] = "Bearer " + key
            if (self.settings.get("provider") or "") == "openrouter":
                headers["HTTP-Referer"] = "https://github.com/saeedsly/dastyarcode"
                headers["X-Title"] = "Dastyar"
        return headers

    def _payload(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]],
                 stream: bool, temperature: Optional[float]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.settings.get("model") or "gpt-4o-mini",
            "messages": messages,
            "stream": bool(stream),
        }
        temp = self.settings.get("temperature", 0.3) if temperature is None else temperature
        try:
            payload["temperature"] = float(temp)
        except Exception:
            payload["temperature"] = 0.3
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _open(self, payload: Dict[str, Any]):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint(), data=data, headers=self._headers(), method="POST"
        )
        return urllib.request.urlopen(req, timeout=self.timeout)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """One completion. Returns an assistant message dict.

        If ``on_delta`` is given the answer is streamed and every text chunk is
        passed to it.  Retries transient errors with backoff.
        """
        provider = self.settings.get("provider") or "openai"
        if provider == "demo" or not self.settings.base_url:
            if provider != "demo":
                raise LLMError(
                    "آدرسِ سرور مدل خالی است. در تنظیمات یک ارائه‌دهنده انتخاب کن "
                    "یا حالت نمایشی را روشن کن."
                )
            from .demo import demo_reply

            return demo_reply(messages, tools)

        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                if on_delta is not None:
                    return self._stream(messages, tools, on_delta, temperature)
                return self._once(messages, tools, temperature)
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:
                    pass
                msg = _friendly_http_error(exc.code, body, provider)
                if exc.code in (401, 402, 403, 404):
                    raise LLMError(msg, exc.code)
                last_err = LLMError(msg, exc.code)
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                last_err = LLMError(
                    "به سرور مدل وصل نشدم (%s). اینترنت، فیلترشکن/VPN یا آدرس سرور را بررسی کن."
                    % (getattr(exc, "reason", exc),)
                )
            except LLMError:
                raise
            except Exception as exc:  # pragma: no cover
                last_err = LLMError("خطای پیش‌بینی‌نشده در ارتباط با مدل: %s" % exc)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        raise last_err or LLMError("ارتباط با مدل برقرار نشد.")

    # ------------------------------------------------------------------ #
    def _once(self, messages, tools, temperature) -> Dict[str, Any]:
        payload = self._payload(messages, tools, False, temperature)
        with self._open(payload) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            raise LLMError("پاسخ سرور JSON معتبر نبود: %s" % raw[:300])
        if "error" in data and not data.get("choices"):
            err = data["error"]
            raise LLMError(str(err.get("message") if isinstance(err, dict) else err))
        return self._normalize(data)

    @staticmethod
    def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("مدل هیچ پاسخی برنگرداند: %s" % str(data)[:300])
        msg = choices[0].get("message") or {}
        out: Dict[str, Any] = {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        if reasoning:
            out["reasoning"] = reasoning
        if data.get("usage"):
            out["usage"] = data["usage"]
        return out

    def _stream(self, messages, tools, on_delta, temperature) -> Dict[str, Any]:
        payload = self._payload(messages, tools, True, temperature)
        content: List[str] = []
        reasoning: List[str] = []
        calls: Dict[int, Dict[str, Any]] = {}
        provider = self.settings.get("provider") or "openai"
        try:
            resp = self._open(payload)
        except urllib.error.HTTPError as exc:
            # some local servers ignore stream=true — retry non-streaming once
            if exc.code in (400, 422):
                return self._once(messages, tools, temperature)
            raise
        with resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                except Exception:
                    continue
                if data.get("error"):
                    err = data["error"]
                    raise LLMError(str(err.get("message") if isinstance(err, dict) else err))
                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        content.append(piece)
                        try:
                            on_delta(piece)
                        except Exception:
                            pass
                    rpiece = delta.get("reasoning_content") or delta.get("reasoning")
                    if rpiece:
                        reasoning.append(rpiece)
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index") or 0)
                        slot = calls.setdefault(
                            idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
        out: Dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content),
            "tool_calls": [calls[i] for i in sorted(calls)],
        }
        for i, c in enumerate(out["tool_calls"]):
            if not c.get("id"):
                c["id"] = "call_%d_%d" % (int(time.time()), i)
        if reasoning:
            out["reasoning"] = "".join(reasoning)
        return out

    # ------------------------------------------------------------------ #
    def test_connection(self) -> Dict[str, Any]:
        """Cheap round-trip used by the settings screen."""
        started = time.time()
        try:
            reply = self.chat(
                [
                    {"role": "system", "content": "Reply with exactly: OK"},
                    {"role": "user", "content": "ping"},
                ],
                tools=None,
                temperature=0,
            )
            return {
                "ok": True,
                "latency_ms": int((time.time() - started) * 1000),
                "reply": (reply.get("content") or "").strip()[:80],
                "model": self.settings.get("model"),
            }
        except LLMError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stream_text(
        self, messages: List[Dict[str, Any]], temperature: Optional[float] = None
    ) -> Iterator[str]:
        """Simple text-only streaming iterator (used by summarisers)."""
        queue: List[str] = []
        result = self.chat(messages, tools=None, on_delta=queue.append, temperature=temperature)
        if queue:
            for piece in queue:
                yield piece
        elif result.get("content"):
            yield result["content"]
