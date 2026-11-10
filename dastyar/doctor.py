"""``dastyar doctor`` — checks everything and prints fixes."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
from pathlib import Path
from typing import List, Tuple

from . import __version__
from .config import (
    IS_LINUX,
    IS_MAC,
    IS_WINDOWS,
    PROVIDERS,
    data_dir,
    os_label,
    which,
)
from .utils import human_size, run

OK = "✅"
WARN = "⚠️"
BAD = "❌"


def _check_network(host: str = "api.openai.com") -> bool:
    try:
        socket.create_connection((host, 443), timeout=4).close()
        return True
    except Exception:
        return False


def run_doctor(settings) -> int:
    print("\n🩺 دستیار — بررسی سلامت (Doctor)\n" + "─" * 46)
    problems: List[Tuple[str, str]] = []
    py = sys.version_info
    print("%s پایتون: %s.%s.%s (%s)" % (
        OK if py >= (3, 7) else BAD, py.major, py.minor, py.micro, sys.executable))
    if py < (3, 7):
        problems.append(("پایتون قدیمی", "پایتون ۳.۷ به بالا نصب کن"))

    print("%s سیستم‌عامل: %s" % (OK, os_label()))
    print("%s معماری: %s" % (OK, platform.machine() or "?"))

    # data folder
    try:
        test_file = data_dir() / ".write-test"
        data_dir().mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print("%s پوشه‌ی داده: %s" % (OK, data_dir()))
    except Exception as exc:
        print("%s پوشه‌ی داده قابل نوشتن نیست: %s" % (BAD, exc))
        problems.append(("مجوز پوشه", "برنامه را با کاربر عادی اجرا کن یا پوشه را دستی بساز"))

    # config
    provider = settings.get("provider")
    info = PROVIDERS.get(provider) or {}
    print("%s ارائه‌دهنده: %s (%s)" % (OK if info else WARN, provider, info.get("label", "?")))
    print("%s مدل: %s" % (OK if settings.get("model") else WARN, settings.get("model")))
    print("%s کلید API: %s" % ((OK if settings.has_key else WARN),
                               "تنظیم شده" if settings.has_key else "تنظیم نشده"))
    if not settings.has_key:
        problems.append(("کلید API",
                         "dastyar key openrouter  ← یا دمو: dastyar config provider demo"))
    if settings.base_url:
        print("   آدرس سرور: %s" % settings.base_url)

    # internet
    net = _check_network()
    print("%s اینترنت: %s" % ((OK if net else WARN), "وصل" if net else "قطع یا فیلتر"))
    if not net:
        problems.append(("اینترنت", "اتصال یا فیلترشکن را بررسی کن؛ یا از Ollama محلی استفاده کن"))

    # optional tools
    optional = {
        "edge-tts (صدای طبیعی فارسی)": "edge-tts",
        "playwright (مرورگر خودکار)": "playwright",
        "faster-whisper (تبدیل آفلاین صدا)": "faster_whisper",
    }
    for label, module in optional.items():
        try:
            __import__(module)
            print("%s %s: نصب" % (OK, label))
        except Exception:
            print("%s %s: نصب نیست (اختیاری) — pip install %s" % (WARN, label, module))

    for exe, why in (("ffmpeg", "تبدیل صدا/ویدیو"), ("git", "کار با مخازن"), ("magick", "تبدیل عکس")):
        path = which(exe)
        print("%s %s: %s" % ((OK if path else WARN), exe, path or "نصب نیست (%s)" % why))

    # voice engines
    try:
        from . import voice

        engines = voice.available_engines()
        print("%s موتورهای صدا: %s" % (OK if engines["tts"] else WARN,
                                       "، ".join(engines["tts"]) or "هیچ"))
        if IS_WINDOWS and engines.get("tts_voices"):
            fa = [v for v in engines["tts_voices"] if "fa" in v.lower() or "persian" in v.lower()]
            print("   صداهای فارسی ویندوز: %s" % ("، ".join(fa) if fa else "ندارد (نصب کن: Settings > Time & Language > Speech)"))
    except Exception as exc:
        print("%s صدا: %s" % (WARN, exc))

    # port
    port = settings.get("ui.port") or 8577
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", int(port)))
        print("%s پورت %s آزاد است" % (OK, port))
    except OSError:
        print("%s پورت %s اشغال است (برنامه‌ی دیگری در حال اجراست؟)" % (WARN, port))
    finally:
        s.close()

    # disk
    try:
        free = shutil.disk_usage(str(data_dir())).free
        print("%s فضای دیسک: %s" % (OK if free > 500 * 1024 ** 2 else WARN, human_size(free)))
    except Exception:
        pass

    print("─" * 46)
    if problems:
        print("پیشنهادها:")
        for title, fix in problems:
            print("  • %s → %s" % (title, fix))
    else:
        print("🎉 همه‌چیز آماده است. بنویس: dastyar run")
    print()
    return 0
