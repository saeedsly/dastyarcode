"""Windows shell integration with zero dependencies (ctypes only).

Creates a hidden message window that provides:
  * a notification-area (tray) icon with a right-click menu
  * a global hotkey (default Ctrl+Alt+Space) to summon the assistant

Everything is guarded so the app still works if any step fails, and the module
is a no-op on macOS/Linux.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, List, Optional

from .config import IS_WINDOWS

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_HOTKEY = 0x0312
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008

VK_CODES = {"space": 0x20, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
            "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A,
            "f12": 0x7B, "a": 0x41, "q": 0x51, "d": 0x44, "s": 0x53, "w": 0x57, "e": 0x45,
            "win": 0x5B}


def parse_hotkey(spec: str):
    """'ctrl+alt+space' -> (MOD_CONTROL|MOD_ALT, 0x20)"""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    mods = 0
    vk = None
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "meta"):
            mods |= MOD_WIN
        elif p in VK_CODES:
            vk = VK_CODES[p]
        elif len(p) == 1:
            vk = ord(p.upper())
    if vk is None:
        vk = VK_CODES["space"]
    return mods, vk


def enable_dpi_awareness() -> bool:
    """Make the app crisp on high-DPI screens (and not blurry on 4K laptops).

    Uses the Vista/7 API when available and falls back gracefully: calling the
    Per-Monitor-v2 shim on Windows 7 would crash, so every call is guarded.
    """
    if not IS_WINDOWS:
        return False
    try:
        import ctypes

        # PROCESS_PER_MONITOR_DPI_AWARE on Win8.1+, ignored on older systems
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return True
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()   # Vista .. Win8
            return True
        except Exception:
            pass
    except Exception:
        pass
    return False


class WindowsHelper:
    def __init__(self, tooltip: str = "دستیار", icon_path: Optional[str] = None,
                 on_open: Optional[Callable[[], None]] = None,
                 on_quit: Optional[Callable[[], None]] = None,
                 on_hotkey: Optional[Callable[[], None]] = None,
                 hotkey: str = "ctrl+alt+space"):
        self.enabled = IS_WINDOWS
        self.tooltip = tooltip
        self.icon_path = icon_path
        self.on_open = on_open or (lambda: None)
        self.on_quit = on_quit or (lambda: None)
        self.on_hotkey = on_hotkey or (lambda: None)
        self.hotkey = hotkey
        self._thread: Optional[threading.Thread] = None
        self._hwnd = None
        self._ready = threading.Event()
        self._menu_ids: List[int] = []
        self._icon_added = False
        self._hotkey_ok = False
        self.error: Optional[str] = None

    # ------------------------------------------------------------------ #
    def start(self) -> bool:
        if not self.enabled:
            return False
        if self._thread and self._thread.is_alive() and self._hwnd:
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="dastyar-tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=4)
        return self._hwnd is not None

    def stop(self, timeout: float = 3.0) -> None:
        """Close the message window and wait for the tray thread to exit.

        Waiting matters: the notification-area icon is removed in the message
        loop, so returning early would leave a ghost icon behind.
        """
        if not self.enabled:
            return
        hwnd = self._hwnd
        thread = self._thread
        if hwnd:
            try:
                ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._hwnd = None
        self._icon_added = False

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self._ready.set()
        finally:
            self._icon_added = False
            self._hwnd = None

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        class_name = "DastyarTrayWindow"
        self_ref = self

        def wndproc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAYICON:
                    low = lparam & 0xFFFF
                    if low in (WM_RBUTTONUP, WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        if low == WM_LBUTTONDBLCLK:
                            threading.Thread(target=self_ref.on_open, daemon=True).start()
                        else:
                            self_ref._show_menu(hwnd)
                    return 0
                if msg == WM_HOTKEY:
                    threading.Thread(target=self_ref.on_hotkey, daemon=True).start()
                    return 0
                if msg == WM_COMMAND:
                    cmd = wparam & 0xFFFF
                    if cmd == 1001:
                        threading.Thread(target=self_ref.on_open, daemon=True).start()
                    elif cmd == 1002:
                        threading.Thread(target=self_ref.on_quit, daemon=True).start()
                    return 0
                if msg == WM_CLOSE:
                    try:
                        user32.UnregisterHotKey(hwnd, 1)
                    except Exception:
                        pass
                    self_ref._remove_icon()
                    user32.DestroyWindow(hwnd)
                    user32.PostQuitMessage(0)
                    self_ref._hwnd = None      # the handle is gone now
                    self_ref._ready.set()      # wake a waiting stop()
                    return 0
                if msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception:
                pass
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_cb = WNDPROC(wndproc)
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = wndproc_cb
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(0, class_name, self.tooltip, 0, 0, 0, 0, 0,
                                      None, None, hinst, None)
        if not hwnd:
            self.error = "CreateWindowEx failed"
            self._ready.set()
            return
        self._hwnd = hwnd

        # --- icon -----------------------------------------------------
        hicon = None
        if self.icon_path:
            try:
                hicon = user32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10)  # LR_LOADFROMFILE|LR_DEFAULTSIZE
            except Exception:
                hicon = None
        if not hicon:
            hicon = user32.LoadIconW(None, ctypes.c_wchar_p(32512))  # IDI_APPLICATION

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = self.tooltip[:120]
        self._icon_added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

        # --- global hotkey --------------------------------------------
        if self.hotkey:
            mods, vk = parse_hotkey(self.hotkey)
            self._hotkey_ok = bool(user32.RegisterHotKey(hwnd, 1, mods, vk))

        self._ready.set()

        # --- message loop ---------------------------------------------
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _remove_icon(self) -> None:
        try:
            if not self._icon_added or not self._hwnd:
                return
            shell32 = ctypes.windll.shell32
            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
            nid.hWnd = self._hwnd
            nid.uID = 1
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self._icon_added = False
        except Exception:
            pass

    def _show_menu(self, hwnd) -> None:
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, 1001, "باز کردن دستیار")
        user32.AppendMenuW(menu, MF_STRING, 1002, "خروج")
        pos = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pos))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                    pos.x, pos.y, 0, hwnd, None)
        if cmd == 1001:
            threading.Thread(target=self.on_open, daemon=True).start()
        elif cmd == 1002:
            threading.Thread(target=self.on_quit, daemon=True).start()
        user32.DestroyMenu(menu)
