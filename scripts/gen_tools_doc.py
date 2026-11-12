#!/usr/bin/env python3
"""Regenerate docs/TOOLS.md from the live tool registry."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dastyar.config import Settings          # noqa: E402
from dastyar.tools import ToolRegistry       # noqa: E402


def short(text: str, limit: int = 120) -> str:
    depth, out = 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch in ".。" and depth == 0:
            break
        out.append(ch)
    result = "".join(out).strip()
    return result if len(result) <= limit else result[: limit - 1] + "…"


def main() -> int:
    reg = ToolRegistry(Settings(Path("/tmp/dastyar-tools-doc.json")))
    items = reg.list_for_ui()
    by_cat = {}
    for t in items:
        by_cat.setdefault(t["category"], []).append(t)
    lines = [
        "# فهرست کامل ابزارها — %d ابزار\n" % len(items),
        "> خودکار از کد تولید شده (`python scripts/gen_tools_doc.py`). "
        "برای دیدن در ترمینال: `dastyar tools`\n",
    ]
    for cat in sorted(by_cat):
        lines.append("\n## %s (%d)\n" % (cat, len(by_cat[cat])))
        lines.append("| ابزار | کار | حساس |")
        lines.append("|---|---|---|")
        for t in sorted(by_cat[cat], key=lambda x: x["name"]):
            lines.append("| `%s` | %s | %s |" % (
                t["name"], short(t["description"]),
                "⚠️" if t["dangerous"] else "—"))
    (ROOT / "docs" / "TOOLS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote docs/TOOLS.md with %d tools" % len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
