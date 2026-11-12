"""Windows GUI automation: keyboard, mouse, windows, windows list.

Uses ctypes (user32) — no pyautogui needed, works on Windows 7..11.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import IS_WINDOWS
from .base import ToolContext, ToolError, tool

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010

    VK = {
        "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
        "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
        "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
        "printscreen": 0x2C, "insert": 0x2D,
    }


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise ToolError("کنترل رابط گرافیکی فقط روی ویندوز پشتیبانی می‌شود.")


def _press_vk(vk: int, up: bool = False) -> None:
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


@tool(
    "type_text",
    "متن را در پنجره‌ی فعال تایپ می‌کند (فارسی و انگلیسی). مثل تایپ در Notepad یا مرورگر.",
    category="کنترل",
    dangerous=True,
    confirm="تایپ در پنجره‌ی فعال (ممکن است در جایی ناخواسته تایپ شود)",
    params={
        "text": {"type": "string"},
        "interval": {"type": "number", "description": "فاصله بین کاراکترها (ثانیه)"},
        "press_enter": {"type": "boolean"},
    },
    required=["text"],
)
def type_text(text: str, interval: float = 0.01, press_enter: bool = False,
              ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    interval = max(0.0, min(0.2, float(interval or 0)))
    for ch in text or "":
        code = ord(ch)
        if ch == "\n":
            _press_vk(VK["enter"]); _press_vk(VK["enter"], True)
        elif ch == "\t":
            _press_vk(VK["tab"]); _press_vk(VK["tab"], True)
        else:
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
        if interval:
            time.sleep(interval)
    if press_enter:
        _press_vk(VK["enter"]); _press_vk(VK["enter"], True)
    return "⌨️ تایپ شد (%d کاراکتر)." % len(text or "")


@tool(
    "press_keys",
    "کلید یا ترکیب کلید می‌زند. مثال: \"ctrl+s\"، \"alt+tab\"، \"win\"، \"enter\"، \"ctrl+shift+esc\".",
    category="کنترل",
    dangerous=True,
    confirm="زدن کلید در پنجره‌ی فعال",
    params={"keys": {"type": "string"}},
    required=["keys"],
)
def press_keys(keys: str, ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    combo = [k.strip().lower() for k in (keys or "").split("+") if k.strip()]
    if not combo:
        raise ToolError("کلیدی مشخص نشد.")
    vks = []
    for k in combo:
        if k in VK:
            vks.append(VK[k])
        elif len(k) == 1:
            vks.append(ord(k.upper()))
        else:
            raise ToolError("کلید ناشناخته: %s" % k)
    for vk in vks:
        _press_vk(vk)
        time.sleep(0.03)
    for vk in reversed(vks):
        _press_vk(vk, True)
        time.sleep(0.03)
    return "🎹 کلید زده شد: %s" % keys


@tool(
    "mouse_action",
    "حرکت/کلیک ماوس. اکشن: move, click, double_click, right_click, scroll, position.",
    category="کنترل",
    dangerous=True,
    confirm="کنترل ماوس (کلیک روی صفحه)",
    params={
        "action": {"type": "string", "enum": ["move", "click", "double_click", "right_click", "scroll", "position"]},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "amount": {"type": "integer", "description": "برای اسکرول؛ مثبت بالا، منفی پایین"},
    },
    required=["action"],
)
def mouse_action(action: str, x: int = 0, y: int = 0, amount: int = 3,
                 ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    if action == "position":
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return "🖱️ مکان ماوس: %d, %d" % (pt.x, pt.y)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    if action == "move":
        return "🖱️ ماوس به %d, %d رفت." % (x, y)
    if action == "scroll":
        user32.mouse_event(0x0800, 0, 0, int(amount or 3) * 120, 0)
        return "🖱️ اسکرول شد."
    if action == "right_click":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        return "🖱️ کلیک راست در %d, %d" % (x, y)
    clicks = 2 if action == "double_click" else 1
    for _ in range(clicks):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.08)
    return "🖱️ کلیک در %d, %d" % (x, y)


def list_windows() -> List[Dict[str, Any]]:
    if not IS_WINDOWS:
        return []
    out: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.strip():
            out.append({"hwnd": int(hwnd), "title": buf.value})
        return True

    user32.EnumWindows(cb, 0)
    return out


@tool(
    "list_windows",
    "فهرست پنجره‌های باز (برنامه‌هایی که الان روی صفحه هستند) را نشان می‌دهد.",
    category="کنترل",
    params={},
)
def list_windows_tool(ctx: Optional[ToolContext] = None) -> str:
    if not IS_WINDOWS:
        return "فهرست پنجره‌ها فقط روی ویندوز در دسترس است."
    wins = list_windows()
    if not wins:
        return "پنجره‌ای پیدا نشد."
    return "🪟 %d پنجره‌ی باز:\n%s" % (len(wins), "\n".join("• %s" % w["title"] for w in wins[:40]))


@tool(
    "focus_window",
    "یک پنجره را با بخشی از عنوانش فعال/بزرگ می‌کند (مثلاً Chrome یا Notepad).",
    category="کنترل",
    dangerous=True,
    confirm="تغییر پنجره‌ی فعال",
    params={"title": {"type": "string"}},
    required=["title"],
)
def focus_window(title: str, ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    needle = (title or "").lower()
    for w in list_windows():
        if needle in w["title"].lower():
            user32.ShowWindow(w["hwnd"], 9)  # SW_RESTORE
            user32.SetForegroundWindow(w["hwnd"])
            return "🪟 پنجره فعال شد: %s" % w["title"]
    raise ToolError("پنجره‌ای با عنوان «%s» پیدا نشد." % title)


@tool(
    "minimize_all",
    "همه‌ی پنجره‌ها را کوچک می‌کند و دسکتاپ را نشان می‌دهد (Win+D).",
    category="کنترل",
    dangerous=True,
    confirm="کوچک کردن همه‌ی پنجره‌ها",
    params={},
)
def minimize_all(ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    for _ in range(2):
        _press_vk(VK["win"]); time.sleep(0.05)
        _press_vk(ord("D")); time.sleep(0.05)
        _press_vk(ord("D"), True); time.sleep(0.05)
        _press_vk(VK["win"], True); time.sleep(0.05)
    return "🖥️ دسکتاپ نمایش داده شد."


@tool(
    "window_snap",
    "پنجره‌ی فعال را به چپ/راست/بالا/پایین می‌چسباند (Win+←/→/↑/↓).",
    category="کنترل",
    dangerous=True,
    confirm="تغییر چیدمان پنجره",
    params={"direction": {"type": "string", "enum": ["left", "right", "maximize", "restore", "minimize"]}},
    required=["direction"],
)
def window_snap(direction: str, ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    keymap = {"left": 0x25, "right": 0x27, "maximize": 0x26, "restore": 0x28, "minimize": 0x28}
    vk = keymap.get(direction)
    if not vk:
        raise ToolError("جهت نامعتبر.")
    _press_vk(VK["win"]); time.sleep(0.05)
    _press_vk(vk); time.sleep(0.05)
    _press_vk(vk, True); time.sleep(0.05)
    _press_vk(VK["win"], True)
    return "🪟 پنجره جابه‌جا شد: %s" % direction


@tool(
    "take_over_text_field",
    "متن را انتخاب، پاک و متن جدید را در فیلد فعال تایپ می‌کند (Ctrl+A سپس تایپ).",
    category="کنترل",
    dangerous=True,
    confirm="جایگزینی متن در فیلد فعال",
    params={"text": {"type": "string"}, "submit": {"type": "boolean"}},
    required=["text"],
)
def take_over_text_field(text: str, submit: bool = False,
                         ctx: Optional[ToolContext] = None) -> str:
    _require_windows()
    _press_vk(VK["ctrl"])
    _press_vk(0x41)  # A
    _press_vk(0x41, True)
    _press_vk(VK["ctrl"], True)
    time.sleep(0.1)
    type_text(text, press_enter=bool(submit))  # type: ignore[call-arg]
    return "⌨️ فیلد فعال پر شد."
