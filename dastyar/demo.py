"""Offline demo brain.

Used when the app runs with ``provider = "demo"`` — no key, no internet.
It produces deterministic, useful answers and actually calls tools so the
whole agent loop can be demonstrated end-to-end.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def _last_user(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _tool_result(messages: List[Dict[str, Any]]) -> Optional[str]:
    for m in reversed(messages):
        if m.get("role") == "tool":
            return m.get("content") or ""
    return None


def _call(name: str, args: Dict[str, Any], idx: int = 0) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "demo_%d" % idx,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    }


HELP = """من دستیار هستم — یک عامل هوشمند محلی روی کامپیوتر خودت. 🖥️

الان در **حالت نمایشی** هستم (بدون کلید API)؛ پس فقط می‌توانم دستورهای ساده را اجرا کنم:
• «آب‌وهوا تهران» / «ساعت چنده»
• «تو دسکتاپ چی هست؟»
• «یک یادداشت با متن ... بساز»
• «یک عکس غروب با هوش مصنوعی بساز» (Picture)
• «فرمان: dir» (در ویندوز)

برای اینکه کامل و هوشمند شوم، در **تنظیمات** یک ارائه‌دهنده (OpenAI / OpenRouter / Gemini / Groq / DeepSeek یا Ollama محلی) و کلیدش را وارد کن؛ بعد از آن می‌توانم فایل‌ها را مدیریت کنم، برنامه باز کنم، در اینترنت جست‌وجو کنم، اکسل و پاورپوینت بسازم، صدا را به متن تبدیل کنم و هر کار دیگری که بخواهی.
"""


def demo_reply(messages: List[Dict[str, Any]], tools: Optional[List[Any]]) -> Dict[str, Any]:
    text = _last_user(messages)
    tool_out = _tool_result(messages)

    # second turn: we already ran a tool -> summarise
    if tool_out is not None and _last_assistant_had_tool(messages):
        snippet = tool_out.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        failed = snippet.lower().startswith(("خطا", "error"))
        head = "⚠️ کامل نشد:\n\n" if failed else "✅ انجام شد:\n\n"
        return {"role": "assistant", "content": head + snippet, "tool_calls": []}

    t = text.lower()
    if not text:
        return {"role": "assistant", "content": HELP, "tool_calls": []}

    if any(k in text for k in ("کمک", "help", "چیکار", "چه کار")):
        return {"role": "assistant", "content": HELP, "tool_calls": []}

    if re.search(r"ساعت|زمان|time", t):
        return _call("clock", {}, 1)

    if re.search(r"تاریخ|امروز چندم", t):
        return _call("today", {}, 2)

    if re.search(r"آب\s*و\s*هوا|هوا|weather", t):
        city = "Tehran"
        m = re.search(r"(تهران|مشهد|اصفهان|شیراز|تبریز|رشت|کرج|قم|اهواز|بندرعباس|یزد|کرمان)", text)
        cities = {
            "تهران": "Tehran", "مشهد": "Mashhad", "اصفهان": "Isfahan", "شیراز": "Shiraz",
            "تبریز": "Tabriz", "رشت": "Rasht", "کرج": "Karaj", "قم": "Qom",
            "اهواز": "Ahvaz", "بندرعباس": "Bandar Abbas", "یزد": "Yazd", "کرمان": "Kerman",
        }
        if m:
            city = cities.get(m.group(1), city)
        return _call("weather", {"city": city}, 3)

    if re.search(r"(دسکتاپ|Desktop).*(چی|چیا|لیست|فایل)|(چی|چیا).*(دسکتاپ|Desktop)", text):
        return _call("list_files", {"path": "~/Desktop"}, 4)

    if "یادداشت" in text or "note" in t:
        body = re.sub(r".*(یادداشت|note)\s*(با|به|:)?\s*", "", text).strip() or "یادداشت خالی"
        return _call("write_note", {"text": body, "title": "یادداشت دستیار"}, 5)

    if re.search(r"(عکس|تصویر|نقاشی).*(بساز|بکش|بده)|generate image", t):
        prompt = re.sub(r".*(بساز|بکش|بده)", "", text).strip()
        prompt = re.sub(r"^(یک|یه)\s*(عکس|تصویر|نقاشی)\s*(از|با)?\s*", "", prompt).strip()
        return _call("generate_image", {"prompt": prompt or "یک منظره‌ی زیبا", "size": "1024x1024"}, 6)

    if re.search(r"^فرمان\s*[::]|^command\s*[::]", text.strip(), re.I):
        cmd = re.sub(r"^(فرمان|command)\s*[::]\s*", "", text, flags=re.I).strip()
        return _call("run_command", {"command": cmd}, 7)

    if re.search(r"(سیستم|ویندوز|سخت.?افزار|رم|cpu|systeminfo)", t):
        return _call("system_info", {}, 8)

    if re.search(r"(پوشه|فایل|folder|file)", t) and re.search(r"(بساز|ایجاد|create)", t):
        return _call("make_folder", {"path": "~/Desktop/پوشه‌ی-جدید"}, 9)

    return {
        "role": "assistant",
        "content": (
            "🧪 الان در **حالت نمایشی** هستم، برای همین فقط دستورهای ساده را می‌فهمم.\n\n"
            "برای اینکه کامل هوشمند شوم یک کلید API در تنظیمات بگذار "
            "(OpenRouter، Gemini و Groq رایگان شروع می‌شوند).\n\n"
            "نمونه دستورهایی که همین حالا کار می‌کنند:\n"
            "• ساعت چنده؟\n• آب‌وهوا شیراز\n• تو دسکتاپ چی هست؟\n"
            "• یک یادداشت با متن «خرید نان» بساز"
        ),
        "tool_calls": [],
    }


def _last_assistant_had_tool(messages: List[Dict[str, Any]]) -> bool:
    for m in reversed(messages):
        if m.get("role") == "tool":
            continue
        if m.get("role") == "assistant":
            return bool(m.get("tool_calls"))
        if m.get("role") == "user":
            return False
    return False
