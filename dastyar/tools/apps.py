"""Open / close applications and Windows settings pages."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Dict, List, Optional

from ..config import IS_MAC, IS_WINDOWS
from ..utils import ensure_dir, expand, os_open, powershell, ps_quote, run
from .base import ToolContext, ToolError, tool

# Friendly name -> executable / launcher (Windows first, then generic)
APP_ALIASES: Dict[str, List[str]] = {
    # browsers
    "مرورگر": ["msedge", "chrome", "firefox"],
    "کروم": ["chrome", "google chrome"],
    "گوگل کروم": ["chrome"],
    "فایرفاکس": ["firefox"],
    "اج": ["msedge"],
    "اج ویندوز": ["msedge"],
    "edge": ["msedge"],
    # office
    "ورد": ["winword"],
    "اکسل": ["excel"],
    "پاورپوینت": ["powerpnt"],
    "پاور پوینت": ["powerpnt"],
    "outlook": ["outlook"],
    "اوت لوک": ["outlook"],
    "یکی نوت": ["onenote"],
    "access": ["msaccess"],
    # windows built-ins
    "نوت": ["notepad"],
    "نوت پد": ["notepad"],
    "notepad": ["notepad"],
    "ماشین حساب": ["calc"],
    "calculator": ["calc"],
    "calc": ["calc"],
    "نقاشی": ["mspaint"],
    "پینت": ["mspaint"],
    "paint": ["mspaint"],
    "تنظیمات": ["ms-settings:"],
    "settings": ["ms-settings:"],
    "پنل کنترل": ["control"],
    "control panel": ["control"],
    "control": ["control"],
    "خط فرمان": ["cmd"],
    "cmd": ["cmd"],
    "پاورشل": ["powershell"],
    "powershell": ["powershell"],
    "ریجستری": ["regedit"],
    "regedit": ["regedit"],
    "تسک منیجر": ["taskmgr"],
    "task manager": ["taskmgr"],
    "taskmgr": ["taskmgr"],
    "اکسپلورر": ["explorer"],
    "فایل منیجر": ["explorer"],
    "explorer": ["explorer"],
    "snip": ["snippingtool"],
    "اسنیپینگ تول": ["snippingtool"],
    "دوربین": ["microsoft.windows.camera:"],
    "camera": ["microsoft.windows.camera:"],
    "ساعت": ["ms-clock:"],
    "آب و هوا": ["bingweather:"],
    "استور": ["ms-windows-store:"],
    "microsoft store": ["ms-windows-store:"],
    # media & messaging
    "vscode": ["code"],
    "وی اس کد": ["code"],
    "vs code": ["code"],
    "تلگرام": ["telegram"],
    "telegram": ["telegram"],
    "واتس اپ": ["whatsapp"],
    "whatsapp": ["whatsapp"],
    "اسپاتیفای": ["spotify"],
    "spotify": ["spotify"],
    "vlc": ["vlc"],
    "دیسکورد": ["discord"],
    "discord": ["discord"],
    "زوم": ["zoom"],
    "zoom": ["zoom"],
    "اسکایپ": ["skype"],
    "skype": ["skype"],
}

MAC_ALIASES = {
    "کروم": "Google Chrome", "chrome": "Google Chrome", "فایرفاکس": "Firefox",
    "سافاری": "Safari", "safari": "Safari", "نوت": "TextEdit", "notepad": "TextEdit",
    "terminal": "Terminal", "ترمینال": "Terminal", "finder": "Finder",
    "settings": "System Settings", "تنظیمات": "System Settings",
}


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace("‌", " ")


def _win_start(target: str, args: str = "") -> bool:
    """Launch via ShellExecute (handles UWP apps, protocols, PATH entries)."""
    script = (
        "Start-Process -FilePath %s" % ps_quote(target)
        + (" -ArgumentList %s" % ps_quote(args) if args else "")
        + " -ErrorAction Stop"
    )
    rc, out, err = powershell(script, timeout=25)
    return rc == 0


@tool(
    "open_app",
    "یک برنامه یا صفحه‌ی ویندوز را باز می‌کند. مثال: کروم، اکسل، نوت، ماشین حساب، تنظیمات، فایل منیجر.",
    category="برنامه",
    params={"name": {"type": "string", "description": "نام برنامه یا مسیر فایل اجرایی"}},
    required=["name"],
)
def open_app(name: str, ctx: Optional[ToolContext] = None) -> str:
    key = _norm(name)
    if not key:
        raise ToolError("نام برنامه خالی است.")
    if IS_WINDOWS:
        candidates = APP_ALIASES.get(key) or APP_ALIASES.get(_norm(name.replace(" ", ""))) or [name]
        for cand in candidates:
            if cand.endswith(":") or cand.startswith("ms-"):
                if _win_start(cand):
                    return "🚀 باز شد: %s" % name
                continue
            try:
                if _win_start(cand):
                    return "🚀 باز شد: %s (%s)" % (name, cand)
            except Exception:
                pass
            for ext in (".exe", ""):
                try:
                    subprocess.Popen([cand + ext], shell=False)
                    return "🚀 باز شد: %s" % name
                except Exception:
                    continue
        # last resort: shell start
        try:
            os.startfile(name)  # type: ignore[attr-defined]
            return "🚀 باز شد: %s" % name
        except Exception as exc:
            raise ToolError(
                "برنامه‌ی «%s» پیدا نشد. شاید نصب نیست. (%s)" % (name, exc)
            )
    if IS_MAC:
        app = MAC_ALIASES.get(key, name)
        rc, _, err = run(["open", "-a", app], timeout=20)
        if rc == 0:
            return "🚀 باز شد: %s" % app
        raise ToolError("برنامه باز نشد: %s" % err.strip())
    # linux
    for cmd in [key, key.replace(" ", "-")]:
        try:
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return "🚀 باز شد: %s" % name
        except Exception:
            continue
    raise ToolError("برنامه‌ی «%s» پیدا نشد." % name)


@tool(
    "close_app",
    "یک برنامه‌ی در حال اجرا را می‌بندد (مثلاً close_app با نام «notepad»).",
    category="برنامه",
    dangerous=True,
    confirm="بستن برنامه‌ی در حال اجرا (ممکن است کار ذخیره‌نشده از دست برود)",
    params={"name": {"type": "string", "description": "نام فرآیند بدون .exe"}},
    required=["name"],
)
def close_app(name: str, ctx: Optional[ToolContext] = None) -> str:
    proc = (name or "").strip()
    if proc.lower().endswith(".exe"):
        proc = proc[:-4]
    if not proc:
        raise ToolError("نام برنامه خالی است.")
    if IS_WINDOWS:
        rc, out, err = run(["taskkill", "/IM", proc + ".exe", "/F"], timeout=20)
        if rc == 0:
            return "🛑 بسته شد: %s" % proc
        raise ToolError("بستن «%s» ناموفق بود: %s" % (proc, (out + err).strip()[:300]))
    rc, out, err = run(["pkill", "-f", proc], timeout=20)
    if rc == 0:
        return "🛑 بسته شد: %s" % proc
    raise ToolError("بستن «%s» ناموفق بود." % proc)


@tool(
    "running_apps",
    "فهرست برنامه‌های در حال اجرا با مصرف حافظه را نشان می‌دهد.",
    category="برنامه",
    params={"limit": {"type": "integer"}},
)
def running_apps(limit: int = 25, ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        script = (
            "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
            "Sort-Object -Property WS -Descending | Select-Object -First %d "
            "Name,Id,@{n='MB';e={[math]::Round($_.WS/1MB)}},MainWindowTitle | "
            "Format-Table -AutoSize | Out-String -Width 160" % int(limit)
        )
        rc, out, err = powershell(script, timeout=30)
        if rc == 0 and out.strip():
            return "🖥️ برنامه‌های باز:\n" + out.strip()
        rc, out, err = run(["tasklist", "/FO", "TABLE"], timeout=20)
        return out.strip()[:4000]
    rc, out, err = run(["ps", "-eo", "comm,pcpu,pmem,args", "--sort=-pmem"], timeout=20)
    return "\n".join(out.splitlines()[: int(limit) + 1])


@tool(
    "open_file",
    "یک فایل یا پوشه را با برنامه‌ی پیش‌فرض ویندوز باز می‌کند.",
    category="برنامه",
    params={"path": {"type": "string"}},
    required=["path"],
)
def open_file(path: str, ctx: Optional[ToolContext] = None) -> str:
    p = expand(path)
    if not p.exists():
        raise ToolError("«%s» وجود ندارد." % p)
    if not os_open(str(p)):
        raise ToolError("باز کردن «%s» ممکن نشد." % p)
    return "📂 باز شد: %s" % p


@tool(
    "open_url",
    "یک آدرس اینترنتی را در مرورگر پیش‌فرض باز می‌کند.",
    category="برنامه",
    params={"url": {"type": "string"}},
    required=["url"],
)
def open_url(url: str, ctx: Optional[ToolContext] = None) -> str:
    url = (url or "").strip()
    if not url:
        raise ToolError("آدرس خالی است.")
    if not url.startswith(("http://", "https://", "mailto:", "tel:")):
        url = "https://" + url
    if not os_open(url):
        raise ToolError("مرورگر باز نشد.")
    return "🌐 در مرورگر باز شد: %s" % url


@tool(
    "open_settings_page",
    "صفحه‌ی مشخصی از تنظیمات ویندوز را باز می‌کند (wifi, bluetooth, display, sound, update, apps, privacy, power).",
    category="برنامه",
    params={
        "page": {
            "type": "string",
            "enum": ["home", "wifi", "bluetooth", "display", "sound", "update", "apps", "privacy",
                     "power", "network", "storage", "mouse", "keyboard", "accounts", "time",
                     "language", "defaultapps", "nightlight"],
        }
    },
    required=["page"],
)
def open_settings_page(page: str, ctx: Optional[ToolContext] = None) -> str:
    mapping = {
        "home": "ms-settings:",
        "wifi": "ms-settings:network-wifi",
        "bluetooth": "ms-settings:bluetooth",
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "update": "ms-settings:windowsupdate",
        "apps": "ms-settings:appsfeatures",
        "privacy": "ms-settings:privacy",
        "power": "ms-settings:batterysaver",
        "network": "ms-settings:network",
        "storage": "ms-settings:storagesense",
        "mouse": "ms-settings:mousetouchpad",
        "keyboard": "ms-settings:keyboard",
        "accounts": "ms-settings:yourinfo",
        "time": "ms-settings:dateandtime",
        "language": "ms-settings:regionlanguage",
        "defaultapps": "ms-settings:defaultapps",
        "nightlight": "ms-settings:nightlight",
    }
    uri = mapping.get((page or "").lower(), "ms-settings:")
    if IS_WINDOWS:
        os.startfile(uri)  # type: ignore[attr-defined]
        return "⚙️ تنظیمات باز شد: %s" % uri
    return "این قابلیت مخصوص ویندوز است."


@tool(
    "browser_new_tab",
    "یک تب جدید در مرورگر پیش‌فرض باز می‌کند (اختیاری با آدرس).",
    category="برنامه",
    params={"url": {"type": "string"}},
)
def browser_new_tab(url: str = "", ctx: Optional[ToolContext] = None) -> str:
    if url and not url.startswith("http"):
        url = "https://" + url
    if not os_open(url or "about:blank"):
        raise ToolError("مرورگر باز نشد.")
    return "🌐 تب جدید باز شد."
