"""Browser control.

Default strategy = "smooth": open the real browser to the URL (fast, robust on
every Windows).  If ``playwright`` is installed the agent can also drive a
headless Chromium (click, fill, extract) — optional upgrade.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, Optional

from ..utils import os_open
from .base import ToolContext, ToolError, tool


def _playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except Exception:
        return None


@tool(
    "browse_to",
    "یک آدرس را در مرورگر باز می‌کند (روش سریع و مطمئن برای همه‌ی ویندوزها).",
    category="اینترنت",
    params={"url": {"type": "string"}},
    required=["url"],
)
def browse_to(url: str, ctx: Optional[ToolContext] = None) -> str:
    url = (url or "").strip()
    if not url:
        raise ToolError("آدرس خالی است.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not os_open(url):
        raise ToolError("مرورگر باز نشد.")
    return "🌐 باز شد: %s" % url


def _headless_available() -> bool:
    return _playwright() is not None


@tool(
    "headless_browse",
    "مرورگر خودکار (بدون پنجره) باز می‌کند، صفحه را می‌خواند یا روی لینک/دکمه کلیک و فرم پر می‌کند. (نیازمند pip install playwright)",
    category="اینترنت",
    dangerous=True,
    confirm="اجرای مرورگر خودکار و تعامل با سایت‌ها",
    params={
        "url": {"type": "string"},
        "action": {"type": "string", "enum": ["text", "screenshot", "click", "fill", "links"]},
        "selector": {"type": "string", "description": "CSS selector برای کلیک/پر کردن"},
        "value": {"type": "string", "description": "مقدار برای پر کردن فرم"},
        "max_chars": {"type": "integer"},
    },
    required=["url"],
)
def headless_browse(url: str, action: str = "text", selector: str = "", value: str = "",
                    max_chars: int = 8000, ctx: Optional[ToolContext] = None) -> str:
    pw = _playwright()
    if pw is None or ctx is None:
        raise ToolError(
            "مرورگر خودکار نصب نیست. برای فعال‌سازی: pip install playwright && playwright install chromium\n"
            "یا از browse_to / fetch_webpage استفاده کن."
        )
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    from ..config import data_dir
    from ..utils import ensure_dir, truncate

    shot_path = str(ensure_dir(data_dir() / "screenshots") / "page.png")
    try:
        with pw() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)
            if action == "text":
                text = page.inner_text("body")
                result = truncate(text, int(max_chars or 8000))
            elif action == "screenshot":
                page.screenshot(path=shot_path, full_page=False)
                if ctx:
                    ctx.attach("image", shot_path)
                result = "📸 اسکرین‌شات صفحه: %s" % shot_path
            elif action == "click":
                if not selector:
                    raise ToolError("برای کلیک، selector لازم است.")
                page.click(selector, timeout=15000)
                page.wait_for_timeout(1500)
                result = "🖱️ کلیک شد. عنوان فعلی: %s" % page.title()
            elif action == "fill":
                if not selector:
                    raise ToolError("برای پر کردن فرم، selector لازم است.")
                page.fill(selector, value or "", timeout=15000)
                result = "⌨️ فیلد پر شد: %s" % selector
            elif action == "links":
                links = page.eval_on_selector_all(
                    "a", "els => els.slice(0,60).map(e => e.innerText.trim() + ' -> ' + e.href)"
                )
                result = "\n".join(links)
            else:
                result = "اکشن نامعتبر."
            browser.close()
            return result
    except Exception as exc:
        raise ToolError("مرورگر خودکار ناموفق بود: %s" % exc)


@tool(
    "browser_status",
    "بررسی می‌کند مرورگر خودکار (Playwright) نصب است یا نه.",
    category="اینترنت",
    params={},
)
def browser_status(ctx: Optional[ToolContext] = None) -> str:
    if _headless_available():
        return "✅ Playwright نصب است؛ مرورگر خودکار فعال است."
    return (
        "⚠️ Playwright نصب نیست. مرورگر خودکار خاموش است، ولی browse_to و fetch_webpage کار می‌کنند.\n"
        "برای فعال‌سازی: pip install playwright && playwright install chromium"
    )
