"""Notes / todo list stored as JSON in the app data folder."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import data_dir
from ..utils import read_json, write_json
from .base import ToolContext, ToolError, tool

NOTES_FILE = data_dir() / "notes.json"


def _load() -> Dict[str, Any]:
    return read_json(NOTES_FILE, {"notes": [], "todos": []}) or {"notes": [], "todos": []}


def _save(data: Dict[str, Any]) -> None:
    write_json(NOTES_FILE, data)


def notes_snapshot() -> Dict[str, Any]:
    return _load()


@tool(
    "write_note",
    "یک یادداشت سریع ذخیره می‌کند (در برنامه هم دیده می‌شود).",
    category="یادداشت",
    params={"text": {"type": "string"}, "title": {"type": "string"}},
    required=["text"],
)
def write_note(text: str, title: str = "یادداشت", ctx: Optional[ToolContext] = None) -> str:
    data = _load()
    note = {"id": int(time.time() * 1000), "title": title or "یادداشت", "text": text,
            "created": time.time()}
    data["notes"].insert(0, note)
    data["notes"] = data["notes"][:500]
    _save(data)
    if ctx:
        ctx.emit({"type": "notes_updated"})
    return "📝 یادداشت ذخیره شد: %s" % (title or note["text"][:40])


@tool(
    "list_notes",
    "یادداشت‌ها و کارهای انجام‌نشده را نشان می‌دهد.",
    category="یادداشت",
    params={"limit": {"type": "integer"}},
)
def list_notes(limit: int = 20, ctx: Optional[ToolContext] = None) -> str:
    data = _load()
    notes = data.get("notes", [])[: int(limit)]
    todos = [t for t in data.get("todos", []) if not t.get("done")]
    lines = ["📝 یادداشت‌ها (%d):" % len(notes)]
    for n in notes:
        lines.append("• [%s] %s — %s" % (time.strftime("%m-%d %H:%M", time.localtime(n["created"])),
                                         n.get("title", ""), (n.get("text", "")[:80])))
    lines.append("")
    lines.append("✅ کارها (%d):" % len(todos))
    for t in todos:
        lines.append("• %s" % t.get("text"))
    return "\n".join(lines)


@tool(
    "add_todo",
    "یک کار به لیست کارها اضافه می‌کند.",
    category="یادداشت",
    params={"text": {"type": "string"}, "due": {"type": "string"}},
    required=["text"],
)
def add_todo(text: str, due: str = "", ctx: Optional[ToolContext] = None) -> str:
    data = _load()
    data.setdefault("todos", []).append(
        {"id": int(time.time() * 1000), "text": text, "due": due, "done": False,
         "created": time.time()}
    )
    _save(data)
    if ctx:
        ctx.emit({"type": "notes_updated"})
    return "✅ به کارها اضافه شد: %s" % text


@tool(
    "complete_todo",
    "یک کار را انجام‌شده علامت می‌زند (جست‌وجو بر اساس متن).",
    category="یادداشت",
    params={"query": {"type": "string"}},
    required=["query"],
)
def complete_todo(query: str, ctx: Optional[ToolContext] = None) -> str:
    data = _load()
    q = (query or "").lower()
    done = 0
    for t in data.get("todos", []):
        if not t.get("done") and q in str(t.get("text", "")).lower():
            t["done"] = True
            done += 1
    _save(data)
    if ctx:
        ctx.emit({"type": "notes_updated"})
    return "✅ %d کار انجام‌شده شد." % done


@tool(
    "delete_note",
    "یک یادداشت را حذف می‌کند.",
    category="یادداشت",
    dangerous=True,
    confirm="حذف یادداشت",
    params={"query": {"type": "string"}},
    required=["query"],
)
def delete_note(query: str, ctx: Optional[ToolContext] = None) -> str:
    data = _load()
    q = (query or "").lower()
    before = len(data.get("notes", []))
    data["notes"] = [n for n in data.get("notes", [])
                     if q not in (str(n.get("title", "")) + str(n.get("text", ""))).lower()]
    _save(data)
    if ctx:
        ctx.emit({"type": "notes_updated"})
    return "🧹 %d یادداشت حذف شد." % (before - len(data["notes"]))
