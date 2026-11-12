"""Reusable "skills": short playbooks injected into the system prompt.

A skill is a name, a list of trigger words (Persian + English) and a prompt
appendix that tells the model exactly which tools to use and in what order.
Users can drop new ``.md`` files in ``<data>/skills`` with a front-matter:

    ---
    name: translate
    triggers: ترجمه, translate, برگردان
    ---
    <prompt text>
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .config import data_dir

BUILTIN: List[Dict[str, Any]] = [
    {
        "name": "ساخت پاورپوینت",
        "triggers": ["پاورپوینت", "ارائه", "پرزنتیشن", "powerpoint", "slides", "presentation"],
        "description": "از هر موضوعی اسلاید حرفه‌ای می‌سازد",
        "prompt": (
            "ابزار: create_powerpoint\n"
            "وقتی کاربر ارائه/پاورپوینت می‌خواهد: ۶ تا ۱۰ اسلاید بساز. اسلاید اول عنوان + زیرعنوان، "
            "بقیه هرکدام یک تیتر کوتاه و ۳ تا ۵ بولت کوتاه (هر بولت زیر ۱۲ کلمه). "
            "مسیر پیش‌فرض ~/Desktop. بعد از ساخت، مسیر فایل را بگو و بپرس باز شود یا نه."
        ),
    },
    {
        "name": "گزارش اکسل",
        "triggers": ["اکسل", "excel", "xlsx", "جدول", "spreadsheet", "گزارش مالی"],
        "description": "جدول و گزارش اکسل واقعی با فرمول",
        "prompt": (
            "ابزار: create_excel یا create_excel_report\n"
            "ردیف اول = سرستون. اعداد را عدد بده (نه رشته). برای جمع از فرمول استفاده کن مثل =SUM(B2:B20). "
            "ستون‌ها را منطقی و کوتاه نام‌گذاری کن."
        ),
    },
    {
        "name": "سند ورد",
        "triggers": ["ورد", "word", "docx", "نامه", "قرارداد", "رزومه", "resume", "cv"],
        "description": "سند متنی رسمی با فرمت Word",
        "prompt": (
            "ابزار: create_word، make_letter، make_resume\n"
            "برای رزومه از make_resume، برای نامه از make_letter و برای سند عمومی از create_word. "
            "تیترها را با # و ## مشخص کن، لیست‌ها با - و جدول را در پارامتر table بده."
        ),
    },
    {
        "name": "جست‌وجوی وب",
        "triggers": ["جستجو", "سرچ", "search", "پیدا کن", "خبر", "قیمت", "آخرین"],
        "description": "اطلاعات تازه از اینترنت",
        "prompt": (
            "ابزارها: web_search → fetch_webpage\n"
            "اول web_search بزن، از نتایج دو یا سه صفحه‌ی مرتبط را با fetch_webpage بخوان، "
            "بعد با ذکر منبع (لینک) جواب بده. اگر نتیجه نبود wikipedia را امتحان کن. "
            "هرگز اطلاعات تازه را از حافظه حدس نزن."
        ),
    },
    {
        "name": "مدیریت فایل",
        "triggers": ["فایل", "پوشه", "file", "folder", "کپی", "جابه‌جا", "حذف", "بکاپ", "backup"],
        "description": "کارهای رایج فایل و پوشه",
        "prompt": (
            "ابزارها: list_files, find_files, copy_file, move_file, delete_file, zip_folder, backup_folder\n"
            "قبل از حذف یا جابه‌جایی حتماً مسیر کامل را با کاربر تأیید کن. "
            "برای حذف پیش‌فرض به سطل بازیافت برو (permanent=false). "
            "قبل از عملیات پرخطر روی پوشه‌ها، اول backup_folder بگیر."
        ),
    },
    {
        "name": "دستیار سیستم",
        "triggers": ["سیستم", "کامپیوتر", "رم", "cpu", "باتری", "فضا", "دیسک", "خراب", "کند", "کندی"],
        "description": "بررسی سلامت و سرعت سیستم",
        "prompt": (
            "ابزارها: system_info, disk_usage, processes_heavy, battery_status, network_speed_test\n"
            "برای «کندِ» سیستم: system_info → processes_heavy(by=cpu) → disk_usage و سپس پیشنهاد عملی بده."
        ),
    },
    {
        "name": "یادآوری",
        "triggers": ["یادآوری", "یادم بنداز", "remind", "امشب", "فردا"],
        "description": "یادآوری زمان‌دار با اعلان",
        "prompt": (
            "ابزار: set_reminder\n"
            "زمان را دقیق تبدیل کن: «نیم ساعت دیگه» → minutes=30، «ساعت ۹ شب» → at=\"21:00\". "
            "بعد از ساخت، زمان دقیق را تأیید کن."
        ),
    },
    {
        "name": "پاکسازی و سرعت ویندوز",
        "triggers": ["پاکسازی", "clean", "temp", "کش", "فایل موقت", "بهینه"],
        "description": "پاک کردن فایل‌های موقت بی‌خطر",
        "prompt": (
            "اول اطلاعات را با run_command ببین (%TEMP%) و فهرست بده، سپس با اجازه‌ی کاربر "
            "پاک کن. هرگز به پوشه‌های سیستمی Windows/System32 دست نزن."
        ),
    },
    {
        "name": "اخلاق و امنیت",
        "triggers": ["رمز", "هک", "کرک", "دور بزن", "bypass"],
        "description": "مرزهای امنیتی",
        "prompt": (
            "هیچ‌وقت برای هک کردن حساب دیگران، دور زدن احراز هویت یا کرک نرم‌افزار کمک نکن. "
            "به جایش راه قانونی و امن پیشنهاد بده (بازیابی حساب، 2FA، ابزارهای رسمی)."
        ),
    },
]


def _load_user_skills() -> List[Dict[str, Any]]:
    folder = data_dir() / "skills"
    out: List[Dict[str, Any]] = []
    if not folder.exists():
        return out
    for path in folder.glob("*.md"):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        name, triggers, body = path.stem, [], raw
        m = re.match(r"(?s)^---\s*(.*?)\s*---\s*(.*)$", raw)
        if m:
            meta, body = m.group(1), m.group(2)
            for line in meta.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key, val = key.strip().lower(), val.strip()
                    if key == "name":
                        name = val
                    elif key == "triggers":
                        triggers = [t.strip() for t in val.split(",") if t.strip()]
        if not triggers:
            triggers = [name]
        out.append({"name": name, "triggers": triggers, "description": "مهارت کاربر",
                    "prompt": body.strip()})
    return out


def all_skills() -> List[Dict[str, Any]]:
    return BUILTIN + _load_user_skills()


def match_skills(text: str, limit: int = 2) -> List[Dict[str, Any]]:
    low = (text or "").lower()
    scored: List[tuple] = []
    for skill in all_skills():
        score = 0
        for trig in skill["triggers"]:
            if trig and trig.lower() in low:
                score += max(1, len(trig) // 3)
        if score:
            scored.append((score, skill))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]
