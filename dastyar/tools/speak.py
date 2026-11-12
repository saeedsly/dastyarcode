"""Voice tools exposed to the agent: speak, listen, transcribe, set voice."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .. import voice
from ..utils import ensure_dir, expand
from .base import ToolContext, ToolError, ToolResult, tool


@tool(
    "speak",
    "متنی را با صدای بلند برای کاربر می‌خواند (فارسی/انگلیسی).",
    category="صدا",
    params={
        "text": {"type": "string"},
        "voice": {"type": "string", "description": "نام صدا (اختیاری)"},
        "engine": {"type": "string", "enum": ["auto", "edge", "sapi", "say", "espeak"]},
    },
    required=["text"],
)
def speak(text: str, voice: str = "", engine: str = "auto",
          ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    if not ctx.settings.get("tts_enabled", True):
        raise ToolError("خواندن صوتی در تنظیمات خاموش است.")
    result = voice.speak(text, voice=voice or ctx.settings.get("tts_voice", ""), engine=engine)
    if not result.get("ok"):
        raise ToolError("خواندن صوتی ناموفق بود: %s" % result.get("error"))
    return "🔊 خوانده شد (موتور %s)." % result.get("engine")


@tool(
    "listen",
    "میکروفون را برای چند ثانیه روشن می‌کند، حرف کاربر را ضبط و به متن تبدیل می‌کند.",
    category="صدا",
    dangerous=True,
    confirm="دسترسی به میکروفون و ضبط صدا",
    params={
        "seconds": {"type": "number", "description": "مدت ضبط (۱ تا ۶۰ ثانیه)"},
        "engine": {"type": "string", "enum": ["auto", "whisper_api", "faster_whisper", "windows"]},
    },
)
def listen(seconds: float = 5.0, engine: str = "auto", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    settings = ctx.settings
    try:
        path = voice.record_microphone(seconds)
    except Exception as exc:
        raise ToolError("ضبط صدا ناموفق بود: %s" % exc)
    ctx.attach("audio", path)
    stt_engine = settings.get("stt_engine", "auto")
    if engine and engine != "auto":
        stt_engine = engine
    result = voice.transcribe(
        path,
        engine="auto" if stt_engine in ("auto", "off") else stt_engine,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.get("stt_model") or "whisper-1",
    )
    if not result.get("ok"):
        raise ToolError("تبدیل گفتار به متن ناموفق: %s" % result.get("error"), output=path)
    return ToolResult("🎤 شنیدم: %s" % result["text"], attach={"kind": "audio", "path": path})


@tool(
    "transcribe_audio",
    "یک فایل صوتی یا ویدیویی را به متن تبدیل می‌کند (mp3, wav, m4a, ogg).",
    category="صدا",
    params={"path": {"type": "string"}},
    required=["path"],
)
def transcribe_audio(path: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    settings = ctx.settings
    p = expand(path)
    if not p.exists():
        raise ToolError("فایل صوتی «%s» پیدا نشد." % p)
    result = voice.transcribe(p, engine=settings.get("stt_engine") if settings.get("stt_engine") != "auto" else "auto",
                              api_key=settings.api_key, base_url=settings.base_url)
    if not result.get("ok"):
        raise ToolError("تبدیل ناموفق: %s" % result.get("error"))
    return "📝 متن (موتور %s):\n\n%s" % (result["engine"], result["text"])


@tool(
    "save_speech",
    "متن را به فایل صوتی تبدیل و ذخیره می‌کند (برای پادکست/ویس).",
    category="صدا",
    dangerous=True,
    confirm="ساخت فایل صوتی",
    params={"text": {"type": "string"}, "path": {"type": "string"}},
    required=["text"],
)
def save_speech_tool(text: str, path: str = "", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = expand(path) if path else Path.home() / "Music" / "dastyar-speech.wav"
    if target.suffix.lower() not in (".wav", ".mp3"):
        target = target.with_suffix(".wav")
    ensure_dir(target.parent)
    try:
        out = voice.save_speech(text, str(target), voice=ctx.settings.get("tts_voice", ""))
    except Exception as exc:
        raise ToolError("ساخت فایل صوتی ناموفق: %s" % exc)
    ctx.attach("audio", out)
    return ToolResult("🎧 فایل صوتی ساخته شد: %s" % out, attach={"kind": "audio", "path": out})


@tool(
    "voice_status",
    "موتورهای صوتی نصب‌شده روی سیستم و صدای‌های موجود را نشان می‌دهد.",
    category="صدا",
    params={},
)
def voice_status(ctx: Optional[ToolContext] = None) -> str:
    info = voice.available_engines()
    tts = "، ".join(info.get("tts") or []) or "هیچ"
    voices = "، ".join(info.get("tts_voices") or []) or "—"
    stt = "، ".join(k for k, v in (info.get("stt") or {}).items() if v) or "هیچ"
    return "🗣️ موتورهای صدا: %s\n🎙️ صداهای نصب‌شده: %s\n📝 تبدیل گفتار: %s" % (tts, voices, stt)
