"""Code execution & scripting (Python / PowerShell / Batch / Shell)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from ..config import IS_MAC, IS_WINDOWS, data_dir
from ..utils import ensure_dir, powershell, run, truncate
from .base import ToolContext, ToolError, tool


@tool(
    "run_command",
    "یک فرمان شل/CMD/PowerShell را اجرا می‌کند و خروجی را برمی‌گرداند. برای کارهای سریع سیستمی.",
    category="کد",
    dangerous=True,
    confirm="اجرای فرمان سیستمی (می‌تواند فایل‌ها را تغییر دهد)",
    params={
        "command": {"type": "string"},
        "shell": {"type": "string", "enum": ["cmd", "powershell", "bash"]},
        "timeout": {"type": "integer", "description": "حداکثر ثانیه (۱ تا ۶۰۰)"},
        "cwd": {"type": "string"},
    },
    required=["command"],
)
def run_command(command: str, shell: str = "", timeout: int = 120, cwd: str = "",
                ctx: Optional[ToolContext] = None) -> str:
    timeout = max(1, min(600, int(timeout or 120)))
    command = (command or "").strip()
    if not command:
        raise ToolError("فرمان خالی است.")
    shell = (shell or "").lower()
    if not shell:
        shell = "cmd" if IS_WINDOWS else "bash"
    if shell == "powershell":
        rc, out, err = powershell(command, timeout=timeout)
    elif shell == "cmd" and IS_WINDOWS:
        rc, out, err = run(["cmd", "/c", command], timeout=timeout, cwd=cwd or None)
    else:
        rc, out, err = run(["bash", "-lc", command] if not IS_WINDOWS else
                           ["cmd", "/c", command], timeout=timeout, cwd=cwd or None)
    text = (out or "") + (("\n[stderr]\n" + err) if err.strip() else "")
    header = "خروجی (کد %d):\n" % rc
    return truncate(header + (text.strip() or "(بدون خروجی)"), 12000)


@tool(
    "run_python",
    "یک قطعه کد پایتون را اجرا می‌کند و نتیجه‌ی چاپ‌شده را برمی‌گرداند. برای محاسبات، پردازش داده و آزمایش کد.",
    category="کد",
    dangerous=True,
    confirm="اجرای کد پایتون روی سیستم",
    params={
        "code": {"type": "string"},
        "timeout": {"type": "integer"},
    },
    required=["code"],
)
def run_python(code: str, timeout: int = 120, ctx: Optional[ToolContext] = None) -> str:
    timeout = max(1, min(600, int(timeout or 120)))
    if not (code or "").strip():
        raise ToolError("کد خالی است.")
    workdir = ensure_dir(data_dir() / "downloads" / "python-tmp")
    script = Path(tempfile.mkstemp(suffix=".py", dir=str(workdir))[1])
    try:
        script.write_text(code, encoding="utf-8")
        rc, out, err = run([sys.executable, "-X", "utf8", str(script)], timeout=timeout, cwd=str(workdir))
        text = (out or "") + (("\n[stderr]\n" + err) if err.strip() else "")
        return truncate("کد خروج: %d\n%s" % (rc, text.strip() or "(بدون خروجی)"), 12000)
    finally:
        try:
            script.unlink()
        except Exception:
            pass


@tool(
    "run_powershell",
    "یک اسکریپت PowerShell را اجرا می‌کند (فقط ویندوز).",
    category="کد",
    dangerous=True,
    confirm="اجرای اسکریپت PowerShell",
    params={"script": {"type": "string"}, "timeout": {"type": "integer"}},
    required=["script"],
)
def run_powershell(script: str, timeout: int = 120,
                   ctx: Optional[ToolContext] = None) -> str:
    rc, out, err = powershell(script, timeout=max(1, min(600, int(timeout or 120))))
    text = (out or "") + (("\n[stderr]\n" + err) if err.strip() else "")
    return truncate("کد خروج: %d\n%s" % (rc, text.strip() or "(بدون خروجی)"), 12000)


@tool(
    "create_and_run_script",
    "یک فایل اسکریپت (.py/.ps1/.bat/.sh) می‌سازد و اجرا می‌کند.",
    category="کد",
    dangerous=True,
    confirm="ساخت و اجرای اسکریپت",
    params={
        "path": {"type": "string"},
        "content": {"type": "string"},
        "run": {"type": "boolean", "description": "اجرا بعد از ساخت"},
    },
    required=["path", "content"],
)
def create_and_run_script(path: str, content: str, run_after: bool = True,
                          ctx: Optional[ToolContext] = None) -> str:
    from ..utils import expand

    p = expand(path)
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")
    if not run_after:
        return "📝 اسکریپت ساخته شد (اجرا نشد): %s" % p
    suffix = p.suffix.lower()
    if suffix == ".py":
        rc, out, err = run([sys.executable, str(p)], timeout=300)
    elif suffix == ".ps1":
        rc, out, err = powershell("& '%s'" % str(p).replace("'", "''"), timeout=300)
    elif suffix == ".bat":
        rc, out, err = run(["cmd", "/c", str(p)], timeout=300)
    else:
        rc, out, err = run(["bash", str(p)], timeout=300)
    text = (out or "") + (("\n[stderr]\n" + err) if err.strip() else "")
    return truncate("اجرا شد (%d):\n%s" % (rc, text.strip() or "(بدون خروجی)"), 12000)


@tool(
    "install_package",
    "یک بسته‌ی پایتون نصب می‌کند (pip). برای قابلیت‌های بیشتر مثل edge-tts یا faster-whisper.",
    category="کد",
    dangerous=True,
    confirm="نصب بسته با pip (از اینترنت دانلود می‌شود)",
    params={"package": {"type": "string", "description": "نام بسته، مثلاً edge-tts"}},
    required=["package"],
)
def install_package(package: str, ctx: Optional[ToolContext] = None) -> str:
    import re

    name = (package or "").strip()
    if not re.match(r"^[A-Za-z0-9_.\-\[\]=<>!~+,]+$", name):
        raise ToolError("نام بسته معتبر نیست.")
    rc, out, err = run([sys.executable, "-m", "pip", "install", "--user", name], timeout=300)
    if rc != 0:
        rc2, out2, err2 = run([sys.executable, "-m", "pip", "install", name], timeout=300)
        out, err, rc = out2, err2, rc2
    return truncate("pip: %s\n%s" % ("موفق" if rc == 0 else "ناموفق", (out or "") + "\n" + (err or "")), 6000)


@tool(
    "explain_code",
    "یک فایل کد را می‌خواند تا درباره‌اش توضیح بدهم (کمکی برای تحلیل).",
    category="کد",
    params={"path": {"type": "string"}, "max_chars": {"type": "integer"}},
    required=["path"],
)
def explain_code(path: str, max_chars: int = 12000, ctx: Optional[ToolContext] = None) -> str:
    from ..utils import expand, truncate

    p = expand(path)
    if not p.exists():
        raise ToolError("فایل «%s» پیدا نشد." % p)
    return truncate(p.read_text(encoding="utf-8", errors="replace"), int(max_chars or 12000))
