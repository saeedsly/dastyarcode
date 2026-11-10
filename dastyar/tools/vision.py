"""Vision tools: look at the screen (OCR-lite via the multimodal model)."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from ..screen import capture_screen
from ..utils import expand
from .base import ToolContext, ToolError, ToolResult, tool


@tool(
    "look_at_screen",
    "از صفحه‌ی نمایش عکس می‌گیرد تا مدل ببیند چه چیزی روی صفحه است (تشخیص خطا، خواندن متن، راهنمایی).",
    category="نمایش",
    params={"question": {"type": "string", "description": "چه چیزی را روی صفحه بررسی کنم؟"}},
)
def look_at_screen(question: str = "روی صفحه چه چیزی می‌بینی؟", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    if not ctx.settings.get("vision", True):
        raise ToolError("قابلیت بینایی در تنظیمات خاموش است.")
    try:
        path = capture_screen(scale=0.75)
    except Exception as exc:
        raise ToolError("عکس‌برداری از صفحه ناموفق بود: %s" % exc)
    if ctx:
        ctx.attach("image", path)
    return ToolResult(
        "📸 تصویر صفحه گرفته شد (برای بررسی توسط مدل بینایی). سؤال: %s" % question,
        attach={"kind": "image", "path": path, "for_model": True},
    )


@tool(
    "describe_image",
    "یک فایل تصویری را برای تحلیل به مدل بینایی می‌فرستد (مثلاً عکس یا اسکرین‌شات روی دیسک).",
    category="نمایش",
    params={"path": {"type": "string"}, "question": {"type": "string"}},
    required=["path"],
)
def describe_image(path: str, question: str = "این تصویر چیست؟", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    p = expand(path)
    if not p.exists():
        raise ToolError("تصویر «%s» پیدا نشد." % p)
    if p.stat().st_size > 20 * 1024 * 1024:
        raise ToolError("تصویر خیلی بزرگ است (بیش از ۲۰ مگابایت).")
    ctx.attach("image", str(p))
    return ToolResult(
        "🖼️ تصویر آماده‌ی تحلیل است. سؤال: %s" % question,
        attach={"kind": "image", "path": str(p), "for_model": True},
    )


def image_to_data_url(path: str) -> str:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "png")
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return "data:image/%s;base64,%s" % (mime, data)
