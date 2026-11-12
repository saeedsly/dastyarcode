"""Small shared helpers (stdlib only)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import IS_MAC, IS_WINDOWS, data_dir, home


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def human_size(num: float) -> str:
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"):
        if abs(num) < 1024.0:
            return "%.1f %s" % (num, unit) if unit != "بایت" else "%d بایت" % num
        num /= 1024.0
    return "%.1f پتابایت" % num


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d ساعت و %d دقیقه" % (h, m)
    if m:
        return "%d دقیقه و %d ثانیه" % (m, s)
    return "%d ثانیه" % s


def truncate(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… [%d کاراکتر دیگر کوتاه شد]" % (len(text) - limit)


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')


def expand(path: str) -> Path:
    if not path:
        return home()
    p = os.path.expandvars(os.path.expanduser(str(path)))
    if len(p) > 1 and p[1] == ":" and not p.endswith(":\\"):
        p = p.rstrip("\\/")
    return Path(p)


def sanitize_filename(name: str, fallback: str = "file") -> str:
    name = _UNSAFE.sub("_", (name or "").strip()).strip(". ")
    return name or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 2
    while True:
        cand = parent / ("%s (%d)%s" % (stem, i, suffix))
        if not cand.exists():
            return cand
        i += 1


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


# --------------------------------------------------------------------------- #
# process helpers
# --------------------------------------------------------------------------- #
def run(
    cmd: List[str],
    timeout: int = 60,
    cwd: Optional[str] = None,
    input_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr) — never raises."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            timeout=timeout,
            env=full_env,
            creationflags=creationflags,
        )
        decode = lambda b: (b or b"").decode("utf-8", "replace")
        return proc.returncode, decode(proc.stdout), decode(proc.stderr)
    except FileNotFoundError:
        return 127, "", "برنامه پیدا نشد: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "زمان اجرا (%d ثانیه) تمام شد." % timeout
    except Exception as exc:  # pragma: no cover
        return 1, "", str(exc)


def powershell(script: str, timeout: int = 60, encoded: bool = False) -> Tuple[int, str, str]:
    """Run a PowerShell script on Windows (no-op error elsewhere)."""
    if not IS_WINDOWS:
        return 127, "", "PowerShell فقط روی ویندوز در دسترس است."
    exe = shutil.which("powershell") or "powershell"
    if encoded:
        import base64

        payload = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        args = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", payload]
    else:
        args = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", script]
    return run(args, timeout=timeout)


def ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def os_open(target: str) -> bool:
    try:
        if IS_WINDOWS:
            os.startfile(target)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", target])
        else:
            for opener in ("xdg-open", "gio", "gnome-open"):
                if shutil.which(opener):
                    subprocess.Popen([opener, target])
                    return True
            return False
        return True
    except Exception:
        return False


def which(*names: str) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def timestamp(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return time.strftime(fmt, time.localtime())


def now_ms() -> int:
    return int(time.time() * 1000)


def app_files_dir(kind: str) -> Path:
    d = ensure_dir(data_dir() / kind)
    return d


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "بله", "اره", "آره")
    return default


def safe_filename_for(path: str) -> str:
    p = Path(path)
    return sanitize_filename(p.name or "file")
