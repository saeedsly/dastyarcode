"""Settings, paths and cross-Windows compatibility helpers.

Everything is standard-library only so the app runs on a bare Python 3.7+
installation on Windows 7 SP1, 8, 8.1, 10 and 11.
"""
from __future__ import annotations

import copy
import json
import os
import platform
import shutil
import sys
import threading
from pathlib import Path

try:  # Python 3.8+
    from typing import Any, Dict, List, Optional
except Exception:  # pragma: no cover
    Any = Dict = List = Optional = object  # type: ignore

APP_NAME = "Dastyar"
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #


def home() -> Path:
    return Path(os.path.expanduser("~"))


def data_dir() -> Path:
    """Per-user writable directory (no admin rights needed on any Windows).

    ``DASTYAR_DATA`` overrides it — used by the portable build and the tests.
    """
    override = os.environ.get("DASTYAR_DATA")
    if override:
        return Path(os.path.expanduser(override))
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return home() / "AppData" / "Roaming" / APP_NAME
    if IS_MAC:
        return home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return Path(base) / "dastyar"


def ensure_data_dir() -> Path:
    d = data_dir()
    for sub in ("sessions", "screenshots", "downloads", "logs", "skills", "voices"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #

DEFAULT_SYSTEM_PROMPT = """تو «دستیار» هستی؛ یک دستیار همه‌کاره، باهوش، صبور و فارسی‌زبان که روی کامپیوتر شخصی کاربر (ویندوز) اجرا می‌شود.

قواعد مهم:
- همیشه به فارسی روان و خودمانی جواب بده، مگر اینکه کاربر زبان دیگری بخواهد.
- کوتاه و مفید بنویس؛ اگر کار چندمرحله‌ای است، مراحل را انجام بده و خلاصه‌ی نتیجه را بگو.
- برای انجام کارها از ابزارها (tools) استفاده کن؛ خودت را جای ابزار نگذار. اگر ابزاری شکست خورد، علت را بگو و راه جایگزین را امتحان کن.
- قبل از کارهای خطرناک (حذف فایل، فرمت، خاموش‌کردن سیستم، تغییر رجیستری، دانلود و اجرای فایل ناشناس) از کاربر تأیید بگیر.
- هیچ‌وقت رمز عبور، کلید API یا اطلاعات خصوصی کاربر را افشا نکن و بدون اجازه به سرورهای ناشناس نفرست.
- وقتی جواب فقط یک جمله است، همان یک جمله را بده. از کلی‌گویی و تعارف اضافه پرهیز کن.
- اگر کاربر گفت «از این به بعد...» یا ترجیحی گفت، با ابزار remember ذخیره کن تا بعداً یادت بماند.
"""

DEFAULTS: Dict[str, Any] = {
    # first run works out of the box in demo mode; the UI offers a one-click
    # switch to a real provider as soon as a key is entered
    "provider": "demo",
    "model": "demo",
    "base_url": None,
    "api_key": "",
    "temperature": 0.3,
    "max_steps": 24,
    "policy": "ask",  # ask | auto | readonly
    "allowed_paths": ["~/Desktop", "~/Documents", "~/Downloads", "~/Pictures"],
    "allow_all_paths": False,
    "user_name": "",
    "language": "fa",
    "vision": True,
    "tts_enabled": True,
    "tts_engine": "auto",  # auto | sapi | edge | say | espeak | off
    "tts_voice": "",
    "stt_engine": "auto",  # auto | windows | openai | whisper | off
    "web_search": {"provider": "duckduckgo", "api_key": ""},
    # 127.0.0.1 keeps the assistant private to this PC: no firewall prompt and
    # nobody else on the network can drive your computer.  Set "0.0.0.0" (or
    # `dastyar serve --host 0.0.0.0 --token ...`) only if you really want the
    # phone-on-same-Wi-Fi setup.
    "ui": {"port": 8577, "host": "127.0.0.1", "open_browser": True, "theme": "auto",
           "token": ""},
    "hotkey": "ctrl+alt+space",
    "system_prompt": "",
    "auto_skills": True,
}

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        "keys_url": "https://platform.openai.com/api-keys",
        "vision": True,
    },
    "openrouter": {
        "label": "OpenRouter (صدها مدل با یک کلید)",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "anthropic/claude-sonnet-4.5",
            "openai/gpt-4o-mini",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat-v3",
            "qwen/qwen3-235b-a22b",
            "meta-llama/llama-3.3-70b-instruct",
        ],
        "keys_url": "https://openrouter.ai/keys",
        "vision": True,
    },
    "groq": {
        "label": "Groq (خیلی سریع و رایگان)",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
        "keys_url": "https://console.groq.com/keys",
        "vision": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "keys_url": "https://platform.deepseek.com/api_keys",
        "vision": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "keys_url": "https://aistudio.google.com/apikey",
        "vision": True,
    },
    "mistral": {
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-latest", "mistral-small-latest"],
        "keys_url": "https://console.mistral.ai/api-keys/",
        "vision": False,
    },
    "ollama": {
        "label": "Ollama (کاملاً آفلاین و رایگان)",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen3:8b", "llama3.2:3b", "gemma3:4b", "deepseek-r1:8b"],
        "keys_url": "https://ollama.com/download",
        "vision": False,
        "no_key": True,
    },
    "lmstudio": {
        "label": "LM Studio (مدل محلی)",
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model"],
        "keys_url": "https://lmstudio.ai",
        "vision": False,
        "no_key": True,
    },
    "custom": {
        "label": "سازگار با OpenAI (آدرس دلخواه)",
        "base_url": "",
        "models": [],
        "keys_url": "",
        "vision": True,
    },
    "demo": {
        "label": "حالت نمایشی (بدون کلید و بدون اینترنت)",
        "base_url": "",
        "models": ["demo"],
        "keys_url": "",
        "vision": False,
        "no_key": True,
    },
}


# --------------------------------------------------------------------------- #
# Settings object
# --------------------------------------------------------------------------- #


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Thread-safe JSON settings with atomic writes."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config_path()
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    # -- io ----------------------------------------------------------------
    def load(self) -> "Settings":
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = _deep_merge(DEFAULTS, raw)
            except FileNotFoundError:
                pass
            except Exception:
                # corrupt config -> keep defaults, back up the broken file
                try:
                    self.path.rename(self.path.with_suffix(".broken.json"))
                except Exception:
                    pass
        return self

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                try:
                    os.chmod(str(tmp), 0o600)
                except Exception:
                    pass
                os.replace(str(tmp), str(self.path))
            except Exception:
                # last-resort non-atomic write
                self.path.write_text(
                    json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    # -- access ------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            cur: Any = self.data
            for part in key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return default
            return cur

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = key.split(".")
            cur = self.data
            for part in parts[:-1]:
                nxt = cur.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[part] = nxt
                cur = nxt
            cur[parts[-1]] = value
        if save:
            self.save()

    def update(self, values: Dict[str, Any], save: bool = True) -> None:
        for k, v in (values or {}).items():
            self.set(k, v, save=False)
        if save:
            self.save()

    # -- derived helpers ---------------------------------------------------
    @property
    def provider_info(self) -> Dict[str, Any]:
        name = self.get("provider") or "openai"
        return PROVIDERS.get(name, PROVIDERS["openai"])

    @property
    def base_url(self) -> str:
        return (self.get("base_url") or self.provider_info.get("base_url") or "").rstrip("/")

    @property
    def api_key(self) -> str:
        from .secret import unprotect

        return unprotect(self.get("api_key") or "")

    @property
    def has_key(self) -> bool:
        if self.provider_info.get("no_key"):
            return True
        return bool(self.api_key)

    @property
    def system_prompt(self) -> str:
        return (self.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT

    @property
    def allowed_paths(self) -> List[Path]:
        out = []
        for p in self.get("allowed_paths") or []:
            try:
                out.append(Path(os.path.expanduser(str(p))).resolve())
            except Exception:
                continue
        return out

    def public_dict(self) -> Dict[str, Any]:
        """Settings safe to send to the browser (no secrets)."""
        with self._lock:
            data = copy.deepcopy(self.data)
        key = data.get("api_key") or ""
        data["api_key"] = ("•" * 8) if key else ""
        data["has_key"] = self.has_key
        data["provider"] = self.get("provider")
        data["provider_label"] = self.provider_info.get("label")
        data["base_url_effective"] = self.base_url
        return data


# --------------------------------------------------------------------------- #
# system facts used in prompts / diagnostics
# --------------------------------------------------------------------------- #


def os_label() -> str:
    if IS_WINDOWS:
        try:
            ver = sys.getwindowsversion()  # type: ignore[attr-defined]
            names = {
                (6, 1): "Windows 7",
                (6, 2): "Windows 8",
                (6, 3): "Windows 8.1",
                (10, 0): "Windows 10/11",
            }
            name = names.get((ver.major, ver.minor), "Windows %d.%d" % (ver.major, ver.minor))
            return "%s (build %s, %s)" % (name, ver.build, platform.machine())
        except Exception:
            return platform.platform()
    return platform.platform()


def find_python() -> str:
    return sys.executable or "python"


def enable_console_safety() -> None:
    """A windowed (console=False) exe has sys.stdout/stderr == None.

    Any ``print`` would then raise AttributeError and kill the app, so we point
    them at a null sink (and keep a log file when one is configured).
    """
    import io

    class _Sink(io.TextIOBase):
        def __init__(self, log_path=None):
            self._log = None
            if log_path:
                try:
                    self._log = open(log_path, "a", encoding="utf-8", errors="replace")
                except OSError:
                    self._log = None

        def write(self, text):  # type: ignore[override]
            if self._log is not None:
                try:
                    self._log.write(text)
                    self._log.flush()
                except OSError:
                    pass
            return len(text)

        def flush(self):  # type: ignore[override]
            if self._log is not None:
                try:
                    self._log.flush()
                except OSError:
                    pass

        def isatty(self):  # type: ignore[override]
            return False

    log = None
    try:
        log_dir = data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = str(log_dir / "dastyar.log")
    except Exception:
        log = None
    if sys.stdout is None:
        sys.stdout = _Sink(log)
    if sys.stderr is None:
        sys.stderr = _Sink(log)

    # Windows terminals default to a legacy code page (cp1252/cp437/cp1256) and
    # a redirected stdout uses the *locale* encoding, so printing Persian would
    # either crash with UnicodeEncodeError or show mojibake.  UTF-8 everywhere.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if IS_WINDOWS:
        try:  # make cmd.exe render the Persian output correctly
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_path(*parts: str) -> Path:
    """Resource that lives next to the app (works for source and PyInstaller).

    PyInstaller collects ``datas`` under ``<root>/dastyar/...``, while a source
    checkout keeps them at ``<root>/dastyar/...`` too, so both spellings are
    tried before falling back to the first candidate.
    """
    root = Path(getattr(sys, "_MEIPASS", app_root()))
    candidates = [root.joinpath(*parts)]
    if parts and parts[0] != "dastyar":
        candidates.append(root.joinpath("dastyar", *parts))
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return candidates[0]


def open_path(path: str) -> None:
    """Open a file/URL with the OS default application."""
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MAC:
        import subprocess

        subprocess.Popen(["open", path])
    else:
        import subprocess

        subprocess.Popen(["xdg-open", path])


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)
