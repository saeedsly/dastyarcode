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


def _declare_winapi():
    """Give ctypes the *correct* 64-bit signatures.

    Without an explicit restype, ctypes assumes C ``int`` (32 bits) and
    silently truncates 64-bit values — a window handle returned by
    CreateWindowExW becomes invalid, so DestroyWindow()/Shell_NotifyIconW()
    fail and the tray icon stays behind.  Also keep *one* reference to the
    WNDPROC callback; if Python garbage-collects it, Windows calls into freed
    memory and CreateWindowExW fails.

    Returns a dict of prepared functions/objects (empty off Windows).
    """
    if not IS_WINDOWS:
        return {}
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
        ]

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE,
                                       ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT,
                                      wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    return {"user32": user32, "shell32": shell32, "kernel32": kernel32,
            "WNDCLASS": WNDCLASS, "NOTIFYICONDATA": NOTIFYICONDATA,
            "WNDPROC": WNDPROC, "LRESULT": LRESULT}


_WINAPI_CACHE = {}


def _winapi():
    if not _WINAPI_CACHE and IS_WINDOWS:
        _WINAPI_CACHE.update(_declare_winapi())
    return _WINAPI_CACHE


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
        self._wndproc_cb = None        # keeps the ctypes callback alive
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
                api = _winapi()
                if api:
                    api["user32"].PostMessageW(hwnd, WM_CLOSE, 0, 0)
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
        api = _winapi()
        if not api:
            self.error = "win32 api unavailable"
            self._ready.set()
            return
        user32 = api["user32"]
        shell32 = api["shell32"]
        kernel32 = api["kernel32"]
        WNDCLASS = api["WNDCLASS"]
        NOTIFYICONDATA = api["NOTIFYICONDATA"]
        WNDPROC = api["WNDPROC"]

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
        self._wndproc_cb = wndproc_cb   # MUST outlive the window
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(wndproc_cb, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(0, class_name, self.tooltip, 0, 0, 0, 0, 0,
                                      None, None, hinst, None)
        if not hwnd:
            err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            self.error = "CreateWindowEx failed (win error %s)" % err
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
            hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(nid)
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
            api = _winapi()
            if not api:
                return
            shell32 = api["shell32"]
            nid = api["NOTIFYICONDATA"]()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self._hwnd
            nid.uID = 1
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self._icon_added = False
        except Exception:
            pass

    def _show_menu(self, hwnd) -> None:
        api = _winapi()
        if not api:
            return
        user32 = api["user32"]
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.TrackPopupMenu.restype = ctypes.c_int
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
        user32.DestroyMenu(ctypes.c_void_p(menu) if isinstance(menu, int) else menu)
