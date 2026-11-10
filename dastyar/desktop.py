"""Desktop launcher: server + window + tray + hotkey.

Order of preference for the app window on Windows:
  1. pywebview  (if the user installed it — gives a real native window)
  2. Edge / Chrome "app mode" (chromeless window, looks like a real app)
  3. default browser tab
On macOS/Linux it simply opens the browser (or a pywebview window if present).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from .config import IS_MAC, IS_WINDOWS, Settings, bundled_path, ensure_data_dir
from .server import serve
from .utils import os_open, run


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _wait_for_server(port: int, seconds: float = 15) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.15)
    return False


def _browser_app_command(url: str) -> Optional[list]:
    """Find a Chromium browser that can open a chromeless app window."""
    if IS_WINDOWS:
        candidates = [
            ("msedge", ["--app=%s" % url, "--window-size=1180,820", "--window-position=80,40",
                        "--user-data-dir=%s" % str(ensure_data_dir() / "ui-profile")]),
        ]
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for exe in ("msedge", "chrome"):
            found = shutil.which(exe)
            if found:
                return [found, "--app=%s" % url, "--window-size=1180,820",
                        "--user-data-dir=%s" % str(ensure_data_dir() / "ui-profile")]
        for path in edge_paths:
            if Path(path).exists():
                return [path, "--app=%s" % url, "--window-size=1180,820",
                        "--user-data-dir=%s" % str(ensure_data_dir() / "ui-profile")]
        return None
    if IS_MAC:
        for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if Path(path).exists():
                return [path, "--app=%s" % url, "--window-size=1180,820"]
        return None
    for exe in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(exe)
        if found:
            return [found, "--app=%s" % url, "--window-size=1180,820"]
    return None


def _open_window(url: str) -> None:
    """Try pywebview -> app-mode browser -> normal browser."""
    try:
        import webview  # type: ignore

        window = webview.create_window("دستیار", url, width=1180, height=830,
                                       min_size=(760, 560), background_color="#070b16")
        webview.start()
        return
    except Exception:
        pass
    cmd = _browser_app_command(url)
    if cmd:
        try:
            kwargs = {}
            if IS_WINDOWS:
                kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
            subprocess.Popen(cmd, **kwargs)
            return
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def launch(settings: Settings, port: Optional[int] = None, open_browser: bool = True,
           tray: bool = True) -> int:
    port = int(port or settings.get("ui.port") or 8577)
    url = "http://127.0.0.1:%d" % port

    server_thread = threading.Thread(
        target=lambda: serve(settings, port=port, open_browser=False, quiet=False),
        name="dastyar-server",
        daemon=True,
    )
    server_thread.start()
    if not _wait_for_server(port):
        print("❌ سرور بالا نیامد. با دستور `dastyar serve` امتحان کن یا `dastyar doctor`.")
        return 1

    # if another instance is already serving, reuse it
    quit_event = threading.Event()

    def open_ui() -> None:
        _open_window(url)

    def do_quit() -> None:
        quit_event.set()
        time.sleep(0.2)
        os._exit(0)

    helper = None
    if tray and IS_WINDOWS:
        try:
            from .winhelp import WindowsHelper

            helper = WindowsHelper(
                tooltip="دستیار — %s" % (settings.get("model") or "AI"),
                icon_path=str(bundled_path("assets", "icon.ico"))
                if bundled_path("assets", "icon.ico").exists() else None,
                on_open=open_ui,
                on_quit=do_quit,
                on_hotkey=open_ui,
                hotkey=settings.get("hotkey") or "ctrl+alt+space",
            )
            helper.start()
        except Exception:
            helper = None

    if open_browser:
        open_ui()

    print("\n  ✅ دستیار آماده است — %s" % url)
    if helper and helper._hwnd:
        print("  🖱️ آیکن در سینی سیستم (کنار ساعت) — راست‌کلیک کن برای منو")
        print("  ⌨️  میان‌بر سراسری: %s" % (settings.get("hotkey") or "ctrl+alt+space"))
    print("  برای بستن: Ctrl+C\n")

    try:
        while not quit_event.is_set():
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    if helper:
        helper.stop()
    print("خداحافظ! 👋")
    return 0


def start_background(settings: Settings, port: Optional[int] = None) -> int:
    """Start just the server without any window (for the installer's startup)."""
    port = int(port or settings.get("ui.port") or 8577)
    serve(settings, port=port, open_browser=False, quiet=False)
    return 0
