"""Developer helpers: git, processes, network ports, env, QR codes, hashing."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import IS_WINDOWS, data_dir
from ..utils import ensure_dir, expand, human_size, powershell, run, truncate, which
from .base import ToolContext, ToolError, ToolResult, tool


@tool(
    "git",
    "دستور git را در یک پوشه اجرا می‌کند (status, log, pull, push, commit, diff...).",
    category="توسعه",
    dangerous=True,
    confirm="اجرای دستور git (ممکن است تاریخچه را تغییر دهد)",
    params={"args": {"type": "string", "description": "مثل «status» یا «log --oneline -5»"},
            "repo": {"type": "string"}},
    required=["args"],
)
def git(args: str, repo: str = "", ctx: Optional[ToolContext] = None) -> str:
    git_exe = which("git")
    if not git_exe:
        raise ToolError("git نصب نیست. از git-scm.com نصب کن.")
    cwd = str(expand(repo)) if repo else None
    rc, out, err = run([git_exe] + args.split(), timeout=180, cwd=cwd)
    return truncate("git %s → کد %d\n%s" % (args, rc, (out + "\n" + err).strip()), 8000)


@tool(
    "list_ports",
    "پورت‌های باز سیستمی و برنامه‌ای که به آن‌ها گوش می‌دهد.",
    category="توسعه",
    params={},
)
def list_ports(ctx: Optional[ToolContext] = None) -> str:
    if IS_WINDOWS:
        rc, out, err = run(["netstat", "-ano"], timeout=30)
    else:
        rc, out, err = run(["ss", "-tulpn"], timeout=30) if which("ss") else run(["netstat", "-tulpn"], timeout=30)
    lines = [l for l in (out or "").splitlines() if "LISTEN" in l.upper() or "LISTENING" in l.upper()]
    return "\n".join(lines[:60]) or "پورت باز پیدا نشد."


@tool(
    "port_check",
    "بررسی می‌کند یک پورت آزاد است یا برنامه‌ای روی آن گوش می‌دهد.",
    category="توسعه",
    params={"port": {"type": "integer"}, "host": {"type": "string"}},
    required=["port"],
)
def port_check(port: int, host: str = "127.0.0.1", ctx: Optional[ToolContext] = None) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        busy = s.connect_ex((host, int(port))) == 0
    finally:
        s.close()
    return "🔒 پورت %d بسته است (برنامه‌ای گوش نمی‌دهد)." % port if not busy else \
        "🟢 پورت %d باز است و برنامه‌ای روی آن گوش می‌دهد." % port


@tool(
    "env_vars",
    "متغیرهای محیطی سیستم را نشان می‌دهد (بدون نمایش مقادیر حساس مثل کلید).",
    category="توسعه",
    params={"filter": {"type": "string"}},
)
def env_vars(filter: str = "", ctx: Optional[ToolContext] = None) -> str:
    f = (filter or "").upper()
    lines = []
    for k, v in sorted(os.environ.items()):
        if f and f not in k.upper():
            continue
        if any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD")):
            v = "••••••"
        lines.append("%s=%s" % (k, v[:120]))
    return "\n".join(lines) or "چیزی پیدا نشد."


@tool(
    "hash_file",
    "هش SHA256 یک فایل را حساب می‌کند (برای بررسی سالم بودن دانلود).",
    category="توسعه",
    params={"path": {"type": "string"}},
    required=["path"],
)
def hash_file(path: str, ctx: Optional[ToolContext] = None) -> str:
    p = expand(path)
    if not p.exists():
        raise ToolError("فایل پیدا نشد.")
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "🔐 SHA256 %s\n%s" % (p.name, h.hexdigest())


@tool(
    "create_qr_code",
    "یک QR کد (SVG) از متن/لینک می‌سازد — بدون اینترنت، با الگوریتم استاندارد.",
    category="توسعه",
    dangerous=True,
    confirm="ساخت فایل QR",
    params={"text": {"type": "string"}, "path": {"type": "string"}, "size": {"type": "integer"}},
    required=["text"],
)
def create_qr_code(text: str, path: str = "", size: int = 320,
                   ctx: Optional[ToolContext] = None) -> ToolResult:
    from ..qr import make_qr_svg

    target = expand(path) if path else data_dir() / "downloads" / ("qr-%s.svg" % __import__("time").strftime("%Y%m%d-%H%M%S"))
    if target.suffix.lower() != ".svg":
        target = target.with_suffix(".svg")
    ensure_dir(target.parent)
    svg = make_qr_svg(text, size=int(size or 320))
    target.write_text(svg, encoding="utf-8")
    if ctx:
        ctx.attach("file", str(target))
    return ToolResult("🔳 QR ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


@tool(
    "json_format",
    "یک متن JSON را مرتب و زیبا می‌کند (یا خطا می‌دهد).",
    category="توسعه",
    params={"text": {"type": "string"}},
    required=["text"],
)
def json_format(text: str, ctx: Optional[ToolContext] = None) -> str:
    try:
        data = json.loads(text)
    except Exception as exc:
        raise ToolError("JSON نامعتبر: %s" % exc)
    return json.dumps(data, ensure_ascii=False, indent=2)


@tool(
    "kill_process_by_port",
    "برنامه‌ای که روی یک پورت اشغال‌شده گوش می‌دهد را می‌بندد (نکته‌ی رایج توسعه‌دهنده‌ها).",
    category="توسعه",
    dangerous=True,
    confirm="بستن برنامه‌ی متصل به پورت",
    params={"port": {"type": "integer"}},
    required=["port"],
)
def kill_process_by_port(port: int, ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        rc, out, err = run(["bash", "-lc", "lsof -ti:%d | xargs -r kill -9" % int(port)], timeout=30)
        return "بسته شد." if rc == 0 else (err or "ناموفق")
    script = (
        "$p=Get-NetTCPConnection -LocalPort %d -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty OwningProcess; "
        "if($p){ Stop-Process -Id $p -Force; 'closed:'+$p } else {'notfound'}" % int(port)
    )
    rc, out, err = powershell(script, timeout=30)
    return out.strip() or (err or "ناموفق")
