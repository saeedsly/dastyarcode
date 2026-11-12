"""Persian messages for the Windows installer (``installer\\install.cmd``).

Batch files are ASCII-only on purpose: Windows 7's cmd.exe cannot render UTF-8
batch files, so all Persian text lives here and is printed by Python, which
speaks UTF-8 natively.  If Python is unavailable (before it is downloaded) the
installer simply falls back to plain English from the .cmd file.

Usage:
    python -m dastyar.installer_ui welcome
    python -m dastyar.installer_ui done
    python -m dastyar.installer_ui doctor
"""
from __future__ import annotations

import os
import sys


def _enable_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


WELCOME = """
  ──────────────────────────────────────────────────────────
   دستیار — دستیار همه‌کاره‌ی هوشمند تو
  ──────────────────────────────────────────────────────────
   • روی همین کامپیوتر نصب می‌شود، بدون دسترسی مدیر
   • ویندوز ۷ SP1 تا ۱۱ (۶۴ بیتی)
   • فایل‌ها، آفیس، PDF فارسی، اینترنت، صدا و تصویر
  ──────────────────────────────────────────────────────────
"""

DONE = """
  ✅ نصب با موفقیت تمام شد!

  میان‌بر «Dastyar» روی دسکتاپ و در منوی Start ساخته شد.

  قدم بعدی:
    ۱) برنامه باز می‌شود → صفحه‌ی «تنظیمات»
    ۲) یکی از دکمه‌های رایگان (OpenRouter / Gemini / Groq) را بزن
    ۳) کلید را بچسبان → ذخیره → تست اتصال
    ۴) برگرد به «گفت‌وگو» و بپرس: «تو دسکتاپ چی هست؟»

  بدون کلید هم «حالت نمایشی» کار می‌کند و می‌توانی برنامه را ببینی.
  راهنمای کامل: README.md  •  بررسی سلامت: Doctor.cmd
"""


UNINSTALL_OK = """
  ✅ دستیار حذف شد.
  گفتگوها و تنظیمات در %APPDATA%\\Dastyar باقی مانده‌اند.
  برای پاک کردن کامل:  Uninstall.cmd /purge
"""

UNINSTALL_PURGED = """
  ✅ دستیار و همه‌ی داده‌ها حذف شدند.
  پوشه‌ی برنامه را هم می‌توانی دستی پاک کنی.
"""


def main(argv: list = None) -> int:
    _enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    what = argv[0] if argv else "welcome"
    if what == "welcome":
        print(WELCOME)
        return 0
    if what == "done":
        print(DONE)
        return 0
    if what == "uninstall":
        purge = any(a.lower() == "/purge" for a in argv[1:])
        try:
            from .config import Settings

            settings = Settings()
            if purge:
                settings.reset()
        except Exception:
            pass
        try:  # shortcuts (same names the installer created)
            import os

            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            links = [os.path.join(desktop, "Dastyar.lnk")]
            appdata = os.environ.get("APPDATA") or ""
            if appdata:
                links.append(os.path.join(appdata, "Microsoft", "Windows",
                                          "Start Menu", "Programs", "Dastyar", "Dastyar.lnk"))
            for link in links:
                if os.path.isfile(link):
                    os.remove(link)
            self_dir = os.path.dirname(links[-1])
            if os.path.isdir(self_dir) and not os.listdir(self_dir):
                os.rmdir(self_dir)
        except Exception:
            pass
        print(UNINSTALL_OK if not purge else UNINSTALL_PURGED)
        return 0

    if what == "doctor":
        from .config import Settings
        from .doctor import run_doctor

        return run_doctor(Settings())
    print("usage: python -m dastyar.installer_ui [welcome|done|doctor]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
