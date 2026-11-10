"""System information & control (power, volume, clipboard, notifications...)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from ..config import IS_MAC, IS_WINDOWS, data_dir, os_label
from ..utils import human_size, ensure_dir, powershell, ps_quote, run, timestamp
from .base import ToolContext, ToolError, tool


def _wmic(query: str) -> str:
    rc, out, err = run(["wmic"] + query.split(), timeout=20)
    return out.strip() if rc == 0 else ""


def _get_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


@tool(
    "system_info",
    "اطلاعات کامل سیستم: ویندوز، پردازنده، حافظه، دیسک و مدت روشن بودن.",
    category="اطلاعات",
    params={},
)
def system_info(ctx: Optional[ToolContext] = None) -> str:
    lines = [
        "🖥️ سیستم‌عامل: %s" % os_label(),
        "🐍 پایتون: %s (%s)" % (platform.python_version(), platform.architecture()[0]),
        "👤 کاربر: %s" % (os.environ.get("USERNAME") or os.environ.get("USER") or "?"),
        "💻 نام دستگاه: %s" % platform.node(),
    ]
    if IS_WINDOWS:
        cpu = _wmic("cpu get Name") or ""
        cores = os.cpu_count()
        mem = _wmic("ComputerSystem get TotalPhysicalMemory")
        lines.append("🧠 پردازنده: %s (%s هسته)" % (cpu.replace("Name", "").strip() or platform.processor(), cores))
        try:
            total = [int(x) for x in mem.split() if x.isdigit()]
            if total:
                lines.append("💾 حافظه: %s" % human_size(total[0]))
        except Exception:
            pass
        rc, out, _ = run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime"], timeout=20)
        if rc == 0 and out.strip():
            lines.append("⏱️ آخرین بوت: %s" % out.strip())
    else:
        lines.append("🧠 پردازنده: %s (%s هسته)" % (platform.processor() or platform.machine(), os.cpu_count()))
    try:
        usage = shutil.disk_usage(str(data_dir().anchor or "/"))
        lines.append("💽 دیسک اصلی: کل %s • آزاد %s" % (human_size(usage.total), human_size(usage.free)))
    except Exception:
        pass
    lines.append("🔑 دسترسی مدیر: %s" % ("دارد" if _get_admin() else "ندارد"))
    return "\n".join(lines)


@tool("today", "تاریخ و روز هفته‌ی امروز (شمسی و میلادی).", category="اطلاعات", params={})
def today(ctx: Optional[ToolContext] = None) -> str:
    gregorian = time.strftime("%Y-%m-%d (%A)")
    jalali = _jalali()
    return "📅 امروز: %s\n🌙 تاریخ شمسی: %s" % (gregorian, jalali)


@tool("clock", "ساعت فعلی سیستم را می‌گوید.", category="اطلاعات", params={})
def clock(ctx: Optional[ToolContext] = None) -> str:
    return "🕐 ساعت: %s" % time.strftime("%H:%M:%S")


def _jalali() -> str:
    """Gregorian -> Jalali conversion without dependencies."""
    import datetime as _dt

    g = _dt.date.today()
    gy, gm, gd = g.year, g.month, g.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = j_day_no // 31 + 1 if j_day_no < 186 else (j_day_no - 186) // 30 + 7
    jd = j_day_no % 31 + 1 if j_day_no < 186 else (j_day_no - 186) % 30 + 1
    months = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر",
              "دی", "بهمن", "اسفند"]
    return "%d %s %d" % (jd, months[jm - 1], jy)


@tool(
    "battery_status",
    "وضعیت شارژ باتری و آداپتور (برای لپ‌تاپ).",
    category="اطلاعات",
    params={},
)
def battery_status(ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        rc, out, _ = powershell(
            "$b=Get-CimInstance Win32_Battery; if($b){'%'+$b.EstimatedChargeRemaining+' | '+"
            "$b.BatteryStatus}else{'بدون باتری'}", timeout=25)
        if rc == 0:
            txt = out.strip()
            if "بدون باتری" in txt:
                return "🔌 این دستگاه باتری ندارد (یا دسکتاپ است)."
            pct = txt.split("|")[0].strip()
            status = "در حال شارژ 🔌" if txt.rstrip().endswith("2") else "روی باتری 🔋"
            return "🔋 شارژ: %s — %s" % (pct, status)
    try:
        with open("/sys/class/power_supply/BAT0/capacity") as fh:
            return "🔋 شارژ: %s%%" % fh.read().strip()
    except Exception:
        return "اطلاعات باتری در دسترس نیست."


@tool(
    "network_speed_test",
    "سرعت تقریبی دانلود اینترنت را اندازه می‌گیرد (با دانلود یک فایل تست کوچک).",
    category="اطلاعات",
    params={},
)
def network_speed_test(ctx: Optional[ToolContext] = None) -> str:
    import time as _t
    import urllib.request

    url = "https://speed.cloudflare.com/__down?bytes=5000000"
    try:
        start = _t.time()
        with urllib.request.urlopen(url, timeout=25) as resp:
            data = resp.read()
        dur = max(_t.time() - start, 0.001)
        mbps = (len(data) * 8 / 1_000_000) / dur
        return "🚀 سرعت دانلود تقریبی: %.2f Mbps (%s در %.1f ثانیه)" % (
            mbps, human_size(len(data)), dur)
    except Exception as exc:
        return "تست سرعت ممکن نشد: %s" % exc


@tool(
    "notification",
    "یک اعلان ویندوز (بالون/توست) نمایش می‌دهد.",
    category="برنامه",
    params={"title": {"type": "string"}, "message": {"type": "string"}},
    required=["title", "message"],
)
def notification(title: str, message: str, ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.Visible=$true;"
            "$n.ShowBalloonTip(8000,%s,%s,[System.Windows.Forms.ToolTipIcon]::Info);"
            "Start-Sleep -Seconds 9; $n.Dispose()"
            % (ps_quote(title), ps_quote(message))
        )
        rc, out, err = powershell(script, timeout=15)
        if rc == 0:
            return "🔔 اعلان نمایش داده شد."
        return "اعلان ممکن نشد: %s" % (err or out)
    return "🔔 %s — %s" % (title, message)


@tool(
    "show_message",
    "یک پنجره‌ی ساده با متن و دکمه‌ی تأیید نشان می‌دهد (کاربر باید ببیند).",
    category="برنامه",
    params={"text": {"type": "string"}, "title": {"type": "string"}},
    required=["text"],
)
def show_message(text: str, title: str = "دستیار", ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "[System.Windows.Forms.MessageBox]::Show(%s,%s) | Out-Null"
            % (ps_quote(text), ps_quote(title))
        )
        rc, out, err = powershell(script, timeout=300)
        return "✅ پیام نمایش داده شد." if rc == 0 else "نمایش پیام ناموفق بود: %s" % err
    return text


@tool(
    "volume_control",
    "کنترل صدا: تنظیم مقدار (۰ تا ۱۰۰)، بی‌صدا، یا افزایش/کاهش.",
    category="برنامه",
    dangerous=True,
    confirm="تغییر مقدار صدای سیستم",
    params={
        "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute", "status"]},
        "level": {"type": "integer", "description": "۰ تا ۱۰۰"},
    },
    required=["action"],
)
def volume_control(action: str, level: int = 20, ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        if action == "set":
            script = (
                "$v=%d; Add-Type -TypeDefinition 'using System.Runtime.InteropServices;"
                "public class V{[DllImport(\"winmm.dll\")] public static extern int waveOutSetVolume(System.IntPtr h,int v);}' ;"
                "[V]::waveOutSetVolume([System.IntPtr]::Zero, ($v -shl 16) -bor $v); 'ok'" % max(0, min(100, int(level)))
            )
        elif action in ("mute", "unmute"):
            script = (
                "(New-Object -ComObject WScript.Shell).SendKeys([char]173); 'ok'"
            )
        else:
            script = "(New-Object -ComObject WScript.Shell).SendKeys([char]175); 'ok'"
        rc, out, err = powershell(script, timeout=20)
        if rc == 0:
            names = {"set": "تنظیم شد روی %d" % level, "up": "صدا بیشتر شد", "down": "صدا کمتر شد",
                     "mute": "بی‌صدا", "unmute": "صدا برگشت", "status": "انجام شد"}
            return "🔊 " + names.get(action, action)
        return "کنترل صدا ناموفق: %s" % err
    if IS_MAC:
        run(["osascript", "-e", "set volume output volume %d" % level])
        return "🔊 صدا تنظیم شد."
    if shutil.which("amixer"):
        run(["amixer", "-q", "sset", "Master", "%d%%" % level])
        return "🔊 صدا تنظیم شد."
    raise ToolError("کنترل صدا در این سیستم پشتیبانی نمی‌شود.")


@tool(
    "lock_screen",
    "صفحه را قفل می‌کند (کاربر باید رمز بزند).",
    category="سیستم",
    dangerous=True,
    confirm="قفل کردن صفحه",
    params={},
)
def lock_screen(ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return "🔒 صفحه قفل شد."
    return "قفل صفحه فقط روی ویندوز پشتیبانی می‌شود."


@tool(
    "power_control",
    "خاموش/ری‌استارت/خواب/هایبرنیت یا لغو خاموشی زمان‌بندی‌شده.",
    category="سیستم",
    dangerous=True,
    confirm="تغییر وضعیت برق سیستم (خاموشی/ری‌استارت/خواب) — کارهای ذخیره‌نشده را از دست می‌دهی!",
    params={
        "action": {"type": "string", "enum": ["shutdown", "restart", "sleep", "hibernate", "cancel"]},
        "delay_seconds": {"type": "integer", "description": "تأخیر، پیش‌فرض ۳۰ ثانیه"},
    },
    required=["action"],
)
def power_control(action: str, delay_seconds: int = 30, ctx: Optional[ToolContext] = None) -> str:
    delay = max(0, int(delay_seconds or 0))
    if IS_WINDOWS:
        cmds = {
            "shutdown": ["shutdown", "/s", "/t", str(delay), "/c", "خاموشی توسط دستیار"],
            "restart": ["shutdown", "/r", "/t", str(delay), "/c", "ری‌استارت توسط دستیار"],
            "hibernate": ["shutdown", "/h"],
            "cancel": ["shutdown", "/a"],
        }
        if action == "sleep":
            rc, out, err = powershell(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false); 'ok'",
                timeout=10,
            )
            return "😴 سیستم به خواب رفت." if rc == 0 else "خواب ناموفق: %s" % err
        cmd = cmds.get(action)
        if not cmd:
            raise ToolError("دستور نامعتبر.")
        rc, out, err = run(cmd, timeout=25)
        if rc == 0:
            msgs = {
                "shutdown": "💤 سیستم تا %d ثانیه دیگر خاموش می‌شود (برای لغو: power_control cancel)." % delay,
                "restart": "🔄 سیستم تا %d ثانیه دیگر ری‌استارت می‌شود." % delay,
                "hibernate": "😴 هایبرنیت انجام شد.",
                "cancel": "✅ خاموشی لغو شد.",
            }
            return msgs.get(action, "انجام شد.")
        raise ToolError("دستور برق ناموفق بود: %s" % (err or out))
    raise ToolError("این قابلیت روی ویندوز طراحی شده است.")


@tool(
    "clipboard_get",
    "محتوای کلیپ‌بورد (چیزی که کپی کرده‌ای) را می‌خواند.",
    category="سیستم",
    params={},
)
def clipboard_get(ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        rc, out, err = powershell("Get-Clipboard -Raw", timeout=20)
        if rc == 0:
            return (out or "").strip()[:8000] or "(کلیپ‌بورد خالی است)"
        return "خواندن کلیپ‌بورد ناموفق: %s" % err
    if IS_MAC:
        rc, out, _ = run(["pbpaste"], timeout=10)
        return out.strip()[:8000] or "(خالی)"
    if shutil.which("xclip"):
        rc, out, _ = run(["xclip", "-selection", "clipboard", "-o"], timeout=10)
        return out.strip()[:8000] or "(خالی)"
    return "کلیپ‌بورد در این سیستم پشتیبانی نمی‌شود."


@tool(
    "clipboard_set",
    "متنی را در کلیپ‌بورد کپی می‌کند تا هر جا خواستی پیست کنی.",
    category="سیستم",
    dangerous=True,
    confirm="جایگزین کردن محتوای کلیپ‌بورد",
    params={"text": {"type": "string"}},
    required=["text"],
)
def clipboard_set(text: str, ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        rc, out, err = powershell("Set-Clipboard -Value %s" % ps_quote(text), timeout=20)
        return "📋 در کلیپ‌بورد کپی شد." if rc == 0 else "کپی ناموفق: %s" % err
    if IS_MAC:
        rc, _, _ = run(["pbcopy"], input_text=text, timeout=10)
        return "📋 کپی شد." if rc == 0 else "کپی ناموفق."
    if shutil.which("xclip"):
        run(["xclip", "-selection", "clipboard"], input_text=text, timeout=10)
        return "📋 کپی شد."
    raise ToolError("کلیپ‌بورد در دسترس نیست.")


@tool(
    "screenshot_notify",
    "صفحه را می‌گیرد و مسیر فایل را برمی‌گرداند (تصویر برای تحلیل هوش مصنوعی).",
    category="نمایش",
    params={"save_to": {"type": "string"}},
)
def screenshot_notify(save_to: str = "", ctx: Optional[ToolContext] = None) -> str:
    from ..screen import capture_screen

    path = capture_screen(save_to or "")
    if ctx:
        ctx.attach("image", path)
    return "📸 تصویر گرفته شد: %s" % path


@tool(
    "processes_heavy",
    "پنج برنامه‌ای که بیشترین حافظه یا CPU را مصرف می‌کنند.",
    category="اطلاعات",
    params={"by": {"type": "string", "enum": ["memory", "cpu"]}},
)
def processes_heavy(by: str = "memory", ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        prop = "WS" if by != "cpu" else "CPU"
        script = (
            "Get-Process | Sort-Object %s -Descending | Select-Object -First 8 "
            "Name,@{n='RAM_MB';e={[math]::Round($_.WS/1MB)}},@{n='CPU_s';e={[math]::Round($_.CPU)}} | "
            "Format-Table -AutoSize | Out-String -Width 120" % prop
        )
        rc, out, _ = powershell(script, timeout=30)
        return "📊 سنگین‌ترین فرآیندها (%s):\n%s" % (by, out.strip())
    rc, out, _ = run(["ps", "-eo", "comm,%mem,%cpu", "--sort=-%mem"], timeout=20)
    return "\n".join(out.splitlines()[:9])
