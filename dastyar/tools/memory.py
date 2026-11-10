"""Long-term memory: facts about the user that survive restarts."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import data_dir
from ..utils import read_json, write_json
from .base import ToolContext, ToolError, tool

MEMORY_FILE = data_dir() / "memory.json"


def load_memory() -> List[Dict[str, Any]]:
    return read_json(MEMORY_FILE, []) or []


def save_memory(items: List[Dict[str, Any]]) -> None:
    write_json(MEMORY_FILE, items[-500:])


def memory_prompt() -> str:
    items = load_memory()
    if not items:
        return ""
    lines = ["چیزهایی که از کاربر می‌دانی (به یاد داشته باش):"]
    for it in items[-40:]:
        lines.append("- %s" % it.get("fact", ""))
    return "\n".join(lines)


@tool(
    "remember",
    "یک واقعیت یا ترجیح درباره‌ی کاربر را برای همیشه ذخیره می‌کند (اسم، شهر، سلیقه، رمزهای غیرحساس...).",
    category="حافظه",
    params={
        "fact": {"type": "string", "description": "جمله‌ی کامل، مثل «اسم کاربر سعید است»"},
        "tag": {"type": "string", "description": "دسته: person, preference, project, ..."},
    },
    required=["fact"],
)
def remember(fact: str, tag: str = "general", ctx: Optional[ToolContext] = None) -> str:
    fact = (fact or "").strip()
    if not fact:
        raise ToolError("متن خالی است.")
    items = load_memory()
    for it in items:
        if it.get("fact", "").strip().lower() == fact.lower():
            it["updated"] = time.time()
            save_memory(items)
            return "🧠 از قبل می‌دانستم."
    items.append({"fact": fact, "tag": tag, "created": time.time()})
    save_memory(items)
    return "🧠 یادم ماند: %s" % fact


@tool(
    "recall",
    "حافظه‌ی بلندمدت را جست‌وجو می‌کند.",
    category="حافظه",
    params={"query": {"type": "string"}},
)
def recall(query: str = "", ctx: Optional[ToolContext] = None) -> str:
    items = load_memory()
    if query:
        q = query.lower()
        items = [i for i in items if q in str(i.get("fact", "")).lower()]
    if not items:
        return "چیزی در حافظه پیدا نشد."
    return "🧠 حافظه:\n%s" % "\n".join(
        "• %s (%s)" % (i.get("fact"), i.get("tag", "-")) for i in items[-50:])


@tool(
    "forget",
    "یک خاطره را از حافظه پاک می‌کند.",
    category="حافظه",
    dangerous=True,
    confirm="پاک کردن یک مورد از حافظه",
    params={"query": {"type": "string", "description": "بخشی از متن خاطره"}},
    required=["query"],
)
def forget(query: str, ctx: Optional[ToolContext] = None) -> str:
    q = (query or "").lower()
    items = load_memory()
    kept = [i for i in items if q not in str(i.get("fact", "")).lower()]
    save_memory(kept)
    removed = len(items) - len(kept)
    return "🧹 %d خاطره پاک شد." % removed
