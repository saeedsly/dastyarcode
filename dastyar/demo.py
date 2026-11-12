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
• «یک فایل PDF / پاورپوینت / اکسل / ورد بساز» (واقعی!)
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

    if re.fullmatch(r"(سلام|درود|سلام علیکم|hi|hello|hey)[!.، ]*", text.strip(), re.I):
        name = ""
        for m in messages:
            if m.get("role") == "system" and "اسم" in (m.get("content") or ""):
                name = " " + (m.get("content") or "").split("اسم")[-1].strip(" :،.")[:20]
                break
        return {
            "role": "assistant",
            "content": ("سلام%s! 👋 من دستیار تو هستم، روی همین کامپیوتر.\n\n"
                        "الان در **حالت نمایشی** هستم (بدون کلید API) ولی همین حالا "
                        "می‌توانم فایل PDF، پاورپوینت، اکسل و ورد بسازم، ساعت و تاریخ "
                        "بگویم، فایل‌های دسکتاپ را نشان بدهم و یادداشت بسازم.\n\n"
                        "چه کاری برایت انجام بدهم؟" % name),
            "tool_calls": [],
        }

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

    # ---- real documents (works offline, great first impression) ----------
    if re.search(r"\bpdf\b|پی\s*دی\s*اف|pdf", t):
        return _call("create_pdf", {
            "title": "هوش مصنوعی در یک نگاه",
            "content": "هوش مصنوعی شاخه‌ای از علوم رایانه است که سیستم‌ها را قادر می‌سازد "
                       "یاد بگیرند، استدلال کنند و تصمیم بگیرند.\n\n"
                       "کاربردهای امروزی:\n- دستیارهای متنی و صوتی\n"
                       "- تشخیص تصویر و گفتار\n- پیش‌بینی و تحلیل داده\n\n"
                       "این فایل نمونه را دستیار در حالت نمایشی ساخت.",
        }, 10)
    if re.search(r"پاور\s*پوینت|powerpoint|pptx|اسلاید", t):
        return _call("create_powerpoint", {
            "title": "هوش مصنوعی",
            "slides": [
                {"title": "مقدمه", "bullets": ["هوش مصنوعی چیست؟", "تاریخچه کوتاه", "چرا مهم است"]},
                {"title": "کاربردها", "bullets": ["پزشکی", "آموزش", "کسب‌وکار", "هنر"]},
                {"title": "جمع‌بندی", "bullets": ["فرصت‌ها", "چالش‌ها", "مسیر بعدی"]},
            ],
        }, 11)
    if re.search(r"اکسل|excel|xlsx|صفحه\s*گسترده", t):
        return _call("create_excel", {
            "rows": [["ماه", "درآمد", "هزینه", "سود"],
                     ["فروردین", 12000000, 8000000, "=B2-C2"],
                     ["اردیبهشت", 14500000, 9100000, "=B3-C3"],
                     ["خرداد", 15200000, 8700000, "=B4-C4"]],
        }, 12)
    if re.search(r"ورد|word|docx|نامه|گزارش\s*(بنویس|بساز|تهیه)", t):
        return _call("create_word", {
            "title": "گزارش نمونه",
            "content": "# خلاصه\nاین گزارش به صورت خودکار توسط دستیار ساخته شد.\n"
                       "## جزئیات\n- مورد اول\n- مورد دوم\n\nپایان گزارش.",
        }, 13)

    if re.search(r"(پوشه|پوشه‌ی|folder)", t) and re.search(r"(بساز|ایجاد|create)", t):
        return _call("make_folder", {"path": "~/Desktop/پوشه‌ی-جدید"}, 9)

    return {
        "role": "assistant",
        "content": (
            "🧪 الان در **حالت نمایشی** هستم، برای همین فقط دستورهای ساده را می‌فهمم.\n\n"
            "برای اینکه کامل هوشمند شوم یک کلید API در تنظیمات بگذار "
            "(OpenRouter، Gemini و Groq رایگان شروع می‌شوند).\n\n"
            "نمونه دستورهایی که همین حالا کار می‌کنند:\n"
            "• ساعت چنده؟\n• آب‌وهوا شیراز\n• تو دسکتاپ چی هست؟\n"
            "• یک فایل PDF درباره هوش مصنوعی بساز\n"
            "• یک پاورپوینت درباره هوش مصنوعی بساز\n"
            "• یک اکسل از هزینه‌های ماه بساز\n"
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
