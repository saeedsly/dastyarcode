"""Scheduling: reminders, task scheduler (Windows), cron-ish "every N minutes" jobs."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import IS_WINDOWS, data_dir
from ..utils import ensure_dir, powershell, ps_quote, read_json, run, write_json
from .base import ToolContext, ToolError, tool

REMINDERS_FILE = data_dir() / "reminders.json"
_TASKS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _load() -> List[Dict[str, Any]]:
    return read_json(REMINDERS_FILE, []) or []


def _save(items: List[Dict[str, Any]]) -> None:
    write_json(REMINDERS_FILE, items)


def _run_reminder_loop() -> None:
    """Background thread that fires due reminders (started by the server)."""
    while True:
        try:
            now = time.time()
            items = _load()
            changed = False
            for item in items:
                if not item.get("done") and item.get("due", 0) <= now:
                    item["done"] = True
                    changed = True
                    _fire(item)
            if changed:
                _save(items)
        except Exception:
            pass
        time.sleep(20)


def _fire(item: Dict[str, Any]) -> None:
    text = "⏰ یادآوری: %s" % item.get("text", "")
    try:
        from .. import voice

        voice.speak(text)
    except Exception:
        pass
    try:
        from .system import notification

        notification("دستیار — یادآوری", item.get("text", ""))
    except Exception:
        pass


_started = False


def start_reminder_thread() -> None:
    global _started
    with _LOCK:
        if _started:
            return
        _started = True
    threading.Thread(target=_run_reminder_loop, daemon=True).start()


def _parse_when(when: str = "", minutes: float = 0, at: str = "") -> float:
    now = dt.datetime.now()
    if minutes:
        return time.time() + float(minutes) * 60
    if at:
        for fmt in ("%H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                parsed = dt.datetime.strptime(at, fmt)
                if fmt == "%H:%M":
                    parsed = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
                    if parsed < now:
                        parsed += dt.timedelta(days=1)
                return parsed.timestamp()
            except ValueError:
                continue
        raise ToolError("قالب زمان نامعتبر است. مثال: 18:30 یا 2026-01-01 09:00")
    if when:
        m = __import__("re").match(r"(\d+)\s*(ثانیه|دقیقه|ساعت|min|sec|hour)", when)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            mult = 1 if unit in ("ثانیه", "sec") else 60 if unit in ("دقیقه", "min") else 3600
            return time.time() + n * mult
    return time.time() + 300


@tool(
    "set_reminder",
    "یادآوری می‌سازد؛ در زمان مقرر اعلان ویندوز و صدا پخش می‌شود.",
    category="زمان‌بندی",
    dangerous=True,
    confirm="ساخت یادآوری زمان‌بندی‌شده",
    params={
        "text": {"type": "string", "description": "متن یادآوری"},
        "minutes": {"type": "number", "description": "چند دقیقه‌ی دیگر"},
        "at": {"type": "string", "description": "ساعت مثل 18:30 یا تاریخ کامل 2026-05-01 09:00"},
        "when": {"type": "string", "description": "مثل «10 دقیقه» یا «2 ساعت»"},
    },
    required=["text"],
)
def set_reminder(text: str, minutes: float = 0, at: str = "", when: str = "",
                 ctx: Optional[ToolContext] = None) -> str:
    due = _parse_when(when, minutes, at)
    items = _load()
    items.append({"text": text, "due": due, "done": False, "created": time.time()})
    _save(items)
    start_reminder_thread()
    return "⏰ یادآوری تنظیم شد برای %s: %s" % (
        time.strftime("%Y-%m-%d %H:%M", time.localtime(due)), text)


@tool(
    "list_reminders",
    "یادآوری‌های فعال را نشان می‌دهد.",
    category="زمان‌بندی",
    params={},
)
def list_reminders(ctx: Optional[ToolContext] = None) -> str:
    items = [i for i in _load() if not i.get("done")]
    if not items:
        return "یادآوری فعالی نداری."
    items.sort(key=lambda x: x.get("due", 0))
    return "⏰ %d یادآوری:\n%s" % (
        len(items),
        "\n".join("• %s — %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(i["due"])),
                                  i.get("text", "")) for i in items),
    )


@tool(
    "clear_reminders",
    "همه‌ی یادآوری‌های فعال را پاک می‌کند.",
    category="زمان‌بندی",
    dangerous=True,
    confirm="پاک کردن همه‌ی یادآوری‌ها",
    params={},
)
def clear_reminders(ctx: Optional[ToolContext] = None) -> str:
    _save([])
    return "🧹 همه‌ی یادآوری‌ها پاک شدند."


@tool(
    "schedule_windows_task",
    "یک تسک در Task Scheduler ویندوز می‌سازد تا برنامه/اسکریپت در زمان مشخص یا هر روز اجرا شود.",
    category="زمان‌بندی",
    dangerous=True,
    confirm="ساخت تسک در زمان‌بند ویندوز",
    params={
        "name": {"type": "string", "description": "نام تسک"},
        "command": {"type": "string", "description": "برنامه یا اسکریپت"},
        "at_time": {"type": "string", "description": "ساعت اجرا مثل 09:00"},
        "daily": {"type": "boolean", "description": "هر روز تکرار شود"},
    },
    required=["name", "command"],
)
def schedule_windows_task(name: str, command: str, at_time: str = "09:00", daily: bool = True,
                          ctx: Optional[ToolContext] = None) -> str:
    at_time = at_time or "09:00"
    if not IS_WINDOWS:
        raise ToolError("Task Scheduler فقط روی ویندوز است.")
    time_val = at_time
    freq = "DAILY" if daily else "ONCE"
    script = (
        "schtasks /Create /TN %s /TR %s /SC %s /ST %s /F"
        % (ps_quote(name), ps_quote(command), freq, ps_quote(str(time_val)))
    )
    rc, out, err = powershell(script, timeout=40)
    if rc != 0 or "SUCCESS" not in out.upper() and "موفق" not in out:
        # schtasks writes localized output; fall back to checking exit code only
        if rc != 0:
            raise ToolError("ساخت تسک ناموفق: %s" % (err or out)[:300])
    return "🗓️ تسک «%s» ساخته شد (%s ساعت %s)." % (name, "هر روز" if daily else "یک‌بار", time_val)


@tool(
    "list_windows_tasks",
    "تسک‌های زمان‌بندی‌شده‌ی ویندوز را فهرست می‌کند.",
    category="زمان‌بندی",
    params={},
)
def list_windows_tasks(ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        return "فقط روی ویندوز."
    rc, out, err = run(["schtasks", "/Query", "/FO", "TABLE"], timeout=40)
    lines = out.splitlines()
    return "\n".join(lines[:40]) if lines else (err or "تسکی نیست.")
