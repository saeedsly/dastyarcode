"""Windows registry read/write (careful: dangerous)."""
from __future__ import annotations

import time
from typing import Optional

from ..config import IS_WINDOWS
from ..utils import powershell, ps_quote
from .base import ToolContext, ToolError, tool

ROOTS = {
    "hkcu": "HKCU:", "hkey_current_user": "HKCU:",
    "hklm": "HKLM:", "hkey_local_machine": "HKLM:",
    "hkcr": "HKCR:", "hkey_classes_root": "HKCR:",
    "hku": "HKU:", "hkey_users": "HKU:",
    "hkcc": "HKCC:", "hkey_current_config": "HKCC:",
}


def _ps_path(path: str) -> str:
    raw = (path or "").strip().replace("\\", "/")
    parts = [p for p in raw.split("/") if p]
    if not parts:
        raise ToolError("مسیر رجیستری خالی است.")
    root = ROOTS.get(parts[0].lower())
    if not root:
        raise ToolError("ریشه‌ی رجیستری نامعتبر است. مثال: HKCU/Software/MyApp")
    return root + "/" + "/".join(parts[1:])


@tool(
    "registry_read",
    "مقدار یک کلید رجیستری ویندوز را می‌خواند. مثال مسیر: HKCU/Software/Microsoft/Windows/CurrentVersion/Explorer",
    category="سیستم",
    params={"path": {"type": "string"}, "name": {"type": "string"}},
    required=["path"],
)
def registry_read(path: str, name: str = "", ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        raise ToolError("رجیستری فقط روی ویندوز است.")
    ps = _ps_path(path)
    script = (
        "$p=%s; if(Test-Path $p){ Get-ItemProperty -Path $p | Format-List | Out-String -Width 200 } else {'کلید پیدا نشد'}"
        % ps_quote(ps)
    )
    if name:
        script = (
            "$v=(Get-ItemProperty -Path %s -Name %s -ErrorAction SilentlyContinue).%s; "
            "if($v -ne $null){$v}else{'مقدار پیدا نشد'}"
            % (ps_quote(ps), ps_quote(name), name)
        )
    rc, out, err = powershell(script, timeout=30)
    if rc != 0:
        raise ToolError("خواندن رجیستری ناموفق: %s" % err[:300])
    return out.strip()[:6000] or "(خالی)"


@tool(
    "registry_write",
    "یک مقدار در رجیستری می‌نویسد (خطرناک؛ قبلاً بکاپ بگیر). نوع: String, DWord, QWord, ExpandString.",
    category="سیستم",
    dangerous=True,
    confirm="نوشتن در رجیستری ویندوز — می‌تواند سیستم را خراب کند!",
    params={
        "path": {"type": "string"},
        "name": {"type": "string"},
        "value": {"type": "string"},
        "type": {"type": "string", "enum": ["String", "DWord", "QWord", "ExpandString"]},
    },
    required=["path", "name", "value"],
)
def registry_write(path: str, name: str, value: str, type: str = "String",
                   ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        raise ToolError("رجیستری فقط روی ویندوز است.")
    ps = _ps_path(path)
    typ = type if type in ("String", "DWord", "QWord", "ExpandString") else "String"
    script = (
        "if(-not (Test-Path %s)){ New-Item -Path %s -Force | Out-Null }; "
        "Set-ItemProperty -Path %s -Name %s -Value %s -Type %s; 'ok'"
        % (ps_quote(ps), ps_quote(ps), ps_quote(ps), ps_quote(name), ps_quote(value), typ)
    )
    rc, out, err = powershell(script, timeout=30)
    if rc != 0 or "ok" not in out:
        raise ToolError("نوشتن رجیستری ناموفق: %s" % (err or out)[:300])
    return "✅ در رجیستری نوشته شد: %s\\%s" % (ps, name)


@tool(
    "registry_backup",
    "از یک کلید رجیستری فایل .reg بکاپ می‌گیرد.",
    category="سیستم",
    dangerous=True,
    confirm="ساخت بکاپ رجیستری",
    params={"path": {"type": "string", "description": "مثل HKCU\\Software\\MyApp"}, "output": {"type": "string"}},
    required=["path"],
)
def registry_backup(path: str, output: str = "", ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        raise ToolError("رجیستری فقط روی ویندوز است.")
    from pathlib import Path

    from ..config import data_dir
    from ..utils import ensure_dir

    import subprocess
    import time as _time

    out = output or str(ensure_dir(data_dir() / "downloads") /
                        ("reg-%s.reg" % _time.strftime("%Y%m%d-%H%M%S")))
    key = (path or "").replace("/", "\\")
    rc = subprocess.run(["reg", "export", key, out, "/y"],
                        capture_output=True, timeout=30).returncode
    if rc != 0:
        raise ToolError("بکاپ رجیستری ناموفق بود.")
    return "💾 بکاپ رجیستری: %s" % out
