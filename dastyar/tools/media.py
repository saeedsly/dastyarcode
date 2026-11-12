"""Images, audio and video: AI image generation, image conversion, TTS, media player."""
from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import IS_MAC, IS_WINDOWS, data_dir
from ..utils import ensure_dir, expand, human_size, os_open, run, unique_path, which
from .base import ToolContext, ToolError, ToolResult, tool


# --------------------------------------------------------------------------- #
# AI image generation
# --------------------------------------------------------------------------- #
@tool(
    "generate_image",
    "با هوش مصنوعی عکس/تصویر می‌سازد (DALL·E / gpt-image / Flux از طریق ارائه‌دهنده). خروجی PNG در Pictures.",
    category="رسانه",
    dangerous=True,
    confirm="ساخت تصویر با هزینه‌ی API و ذخیره روی دیسک",
    params={
        "prompt": {"type": "string", "description": "توصیف دقیق تصویر"},
        "size": {"type": "string", "description": "1024x1024 | 1792x1024 | 1024x1792"},
        "path": {"type": "string"},
    },
    required=["prompt"],
)
def generate_image(prompt: str, size: str = "1024x1024", path: str = "",
                   ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    settings = ctx.settings
    base = settings.base_url
    key = settings.api_key
    if not base:
        raise ToolError("برای ساخت تصویر باید یک ارائه‌دهنده با کلید API تنظیم شود.")
    model = settings.get("image_model") or ""
    target_dir = Path.home() / "Pictures"
    ensure_dir(target_dir)
    target = unique_path(target_dir / ("ai-image-%s.png" % __import__("time").strftime("%Y%m%d-%H%M%S")))

    payload: Dict[str, Any] = {"prompt": prompt, "n": 1, "size": size or "1024x1024"}
    if model:
        payload["model"] = model
    elif "openai.com" in base:
        payload["model"] = "gpt-image-1"
    req = urllib.request.Request(
        base + "/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise ToolError(
            "ساخت تصویر ناموفق بود: %s\n"
            "نکته: مدل‌های OpenRouter تصویر نمی‌سازند؛ از OpenAI یا یک سرویس سازگار استفاده کن." % exc
        )
    item = (data.get("data") or [{}])[0]
    try:
        if item.get("b64_json"):
            target.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=120) as img:
                target.write_bytes(img.read())
        else:
            raise ToolError("پاسخ سرویس تصویر، فایل یا لینکی نداشت.")
    except Exception as exc:
        raise ToolError("ذخیره‌ی تصویر ناموفق بود: %s" % exc)
    ctx.attach("image", str(target))
    return ToolResult("🎨 تصویر ساخته شد: %s" % target,
                      attach={"kind": "image", "path": str(target)})


# --------------------------------------------------------------------------- #
# local picture generation (no API) via SVG
# --------------------------------------------------------------------------- #
@tool(
    "create_simple_svg",
    "بدون اینترنت و API یک تصویر SVG (نمودار/شکل/کارت گرافیکی) می‌سازد.",
    category="رسانه",
    dangerous=True,
    confirm="ساخت فایل SVG",
    params={
        "path": {"type": "string"},
        "title": {"type": "string"},
        "shapes": {
            "type": "array",
            "description": "[{type: rect|circle|line|text, ...}]",
            "items": {"type": "object"},
        },
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "background": {"type": "string"},
    },
    required=["path"],
)
def create_simple_svg(path: str, title: str = "", shapes: Optional[List[Dict[str, Any]]] = None,
                      width: int = 800, height: int = 500, background: str = "#0f172a",
                      ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = expand(path)
    if target.suffix.lower() != ".svg":
        target = target.with_suffix(".svg")
    ensure_dir(target.parent)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
        % (width, height, width, height),
        '<rect width="100%%" height="100%%" fill="%s"/>' % background,
    ]
    if title:
        parts.append(
            '<text x="50%%" y="60" fill="#e2e8f0" font-size="28" font-family="Tahoma" '
            'text-anchor="middle">%s</text>' % _xml(title)
        )
    for s in shapes or []:
        t = (s.get("type") or "").lower()
        fill = s.get("fill", "#3b82f6")
        stroke = s.get("stroke", "none")
        if t == "rect":
            parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s"/>' % (
                s.get("x", 0), s.get("y", 0), s.get("w", 100), s.get("h", 60), s.get("rx", 8), fill, stroke))
        elif t == "circle":
            parts.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s"/>' % (
                s.get("cx", 0), s.get("cy", 0), s.get("r", 40), fill, stroke))
        elif t == "line":
            parts.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s"/>' % (
                s.get("x1", 0), s.get("y1", 0), s.get("x2", 100), s.get("y2", 100),
                s.get("stroke", "#94a3b8"), s.get("width", 2)))
        elif t == "text":
            parts.append('<text x="%s" y="%s" fill="%s" font-size="%s" font-family="Tahoma" '
                         'text-anchor="%s">%s</text>' % (
                             s.get("x", 20), s.get("y", 20), s.get("fill", "#e2e8f0"),
                             s.get("size", 18), s.get("anchor", "start"), _xml(s.get("text", ""))))
    parts.append("</svg>")
    target.write_text("\n".join(parts), encoding="utf-8")
    ctx.attach("file", str(target))
    return ToolResult("🎨 SVG ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


def _xml(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------- #
# convert images (no Pillow) — via Windows .NET or ImageMagick
# --------------------------------------------------------------------------- #
@tool(
    "convert_image",
    "تبدیل فرمت یا تغییر اندازه‌ی تصویر (jpg/png/bmp/webp) — با ابزارهای خود ویندوز یا ImageMagick.",
    category="رسانه",
    dangerous=True,
    confirm="تبدیل و ذخیره‌ی تصویر",
    params={
        "source": {"type": "string"},
        "destination": {"type": "string"},
        "width": {"type": "integer", "description": "۰ = بدون تغییر"},
        "height": {"type": "integer"},
    },
    required=["source", "destination"],
)
def convert_image(source: str, destination: str, width: int = 0, height: int = 0,
                  ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    src = expand(source)
    dst = expand(destination)
    if not src.exists():
        raise ToolError("تصویر «%s» پیدا نشد." % src)
    ensure_dir(dst.parent)
    magick = which("magick", "convert")
    if magick and not IS_WINDOWS:
        args = [magick, str(src)]
        if width or height:
            args += ["-resize", "%sx%s" % (width or "", height or "")]
        args.append(str(dst))
        rc, out, err = run(args, timeout=120)
        if rc == 0:
            ctx.attach("image", str(dst))
            return ToolResult("🖼️ تبدیل شد: %s" % dst, attach={"kind": "image", "path": str(dst)})
    if IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Drawing; "
            "$img=[System.Drawing.Image]::FromFile('%s'); "
            "$w=%d; $h=%d; if($w -le 0){$w=$img.Width}; if($h -le 0){$h=$img.Height}; "
            "$bmp=New-Object System.Drawing.Bitmap($w,$h); "
            "$g=[System.Drawing.Graphics]::FromImage($bmp); "
            "$g.InterpolationMode='HighQualityBicubic'; "
            "$g.DrawImage($img,0,0,$w,$h); "
            "$bmp.Save('%s', [System.Drawing.Imaging.ImageFormat]::%s); "
            "$g.Dispose(); $bmp.Dispose(); $img.Dispose(); 'ok'"
            % (str(src).replace("'", "''"), width, height, str(dst).replace("'", "''"),
               _imformat(dst))
        )
        rc, out, err = run(["powershell", "-NoProfile", "-Command", script], timeout=120)
        if rc == 0 and dst.exists():
            ctx.attach("image", str(dst))
            return ToolResult("🖼️ تبدیل شد: %s" % dst, attach={"kind": "image", "path": str(dst)})
        raise ToolError("تبدیل تصویر ناموفق بود: %s" % (err or out)[:300])
    raise ToolError("ابزار تبدیل تصویر در دسترس نیست.")


def _imformat(path: Path) -> str:
    return {".png": "Png", ".jpg": "Jpeg", ".jpeg": "Jpeg", ".bmp": "Bmp", ".gif": "Gif",
            ".tiff": "Tiff"}.get(path.suffix.lower(), "Png")


# --------------------------------------------------------------------------- #
# audio / video
# --------------------------------------------------------------------------- #
@tool(
    "play_media",
    "یک فایل صوتی یا ویدیویی را با برنامه‌ی پیش‌فرض پخش می‌کند.",
    category="رسانه",
    params={"path": {"type": "string"}},
    required=["path"],
)
def play_media(path: str, ctx: Optional[ToolContext] = None) -> str:
    p = expand(path)
    if not p.exists():
        raise ToolError("فایل «%s» پیدا نشد." % p)
    if not os_open(str(p)):
        raise ToolError("پخش ممکن نشد.")
    return "▶️ در حال پخش: %s" % p


@tool(
    "audio_info",
    "اطلاعات یک فایل صوتی WAV را می‌خواند (مدت، نرخ نمونه‌برداری، کانال).",
    category="رسانه",
    params={"path": {"type": "string"}},
    required=["path"],
)
def audio_info(path: str, ctx: Optional[ToolContext] = None) -> str:
    p = expand(path)
    if not p.exists():
        raise ToolError("فایل پیدا نشد.")
    try:
        with wave.open(str(p), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return "🎵 %s\nمدت: %.1f ثانیه\nنرخ: %d Hz\nکانال: %d\nعمق: %d بیت" % (
                p.name, frames / float(rate or 1), rate, w.getnchannels(), w.getsampwidth() * 8)
    except Exception:
        if which("ffprobe"):
            rc, out, err = run(["ffprobe", "-v", "quiet", "-show_format", "-show_streams", str(p)])
            return out[:2000]
        raise ToolError("خواندن اطلاعات صوتی ممکن نشد.")


@tool(
    "create_tone",
    "یک صدای ساده (بیپ/تون) با فرکانس و مدت مشخص در WAV می‌سازد — برای تست صدا.",
    category="رسانه",
    dangerous=True,
    confirm="ساخت فایل صوتی",
    params={
        "path": {"type": "string"},
        "frequency": {"type": "number"},
        "duration": {"type": "number"},
    },
)
def create_tone(path: str = "", frequency: float = 440.0, duration: float = 1.0,
                ctx: Optional[ToolContext] = None) -> ToolResult:
    import math

    target = expand(path) if path else data_dir() / "downloads" / "tone.wav"
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")
    ensure_dir(target.parent)
    rate = 22050
    n = int(rate * max(0.05, min(30.0, duration)))
    frames = bytearray()
    for i in range(n):
        value = int(12000 * math.sin(2 * math.pi * frequency * i / rate))
        frames += struct.pack("<h", value)
    with wave.open(str(target), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    ctx.attach("file", str(target))  # type: ignore[union-attr]
    return ToolResult("🔔 صدا ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


@tool(
    "convert_media",
    "تبدیل فرمت صدا/ویدیو و استخراج صدا با ffmpeg (اگر نصب باشد).",
    category="رسانه",
    dangerous=True,
    confirm="تبدیل فایل رسانه",
    params={
        "source": {"type": "string"},
        "destination": {"type": "string"},
        "extra_args": {"type": "string", "description": "مثل -ar 16000 -ac 1"},
    },
    required=["source", "destination"],
)
def convert_media(source: str, destination: str, extra_args: str = "",
                  ctx: Optional[ToolContext] = None) -> ToolResult:
    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        raise ToolError("ffmpeg نصب نیست. از سایت ffmpeg.org دانلود کن یا از convert_image استفاده کن.")
    src, dst = expand(source), expand(destination)
    if not src.exists():
        raise ToolError("فایل مبدأ پیدا نشد.")
    ensure_dir(dst.parent)
    args = [ffmpeg, "-y", "-i", str(src)] + (extra_args.split() if extra_args else []) + [str(dst)]
    rc, out, err = run(args, timeout=900)
    if rc != 0:
        raise ToolError("تبدیل ناموفق: %s" % err[-500:])
    ctx.attach("file", str(dst))  # type: ignore[union-attr]
    return ToolResult("🎬 تبدیل شد: %s" % dst, attach={"kind": "file", "path": str(dst)})
