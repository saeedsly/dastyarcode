"""Windows-only checks: tray icon, global hotkey, shortcut target, DPI.

These skip on other platforms but run on the CI Windows runners, which is the
only place where ctypes/user32 behaviour can be verified.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

IS_WINDOWS = sys.platform == "win32"


@unittest.skipUnless(IS_WINDOWS, "Windows-only UI integration")
class TestWindowsHelper(unittest.TestCase):
    def test_hotkey_string_is_parsed(self):
        from dastyar.winhelp import parse_hotkey

        mods, vk = parse_hotkey("ctrl+alt+space")
        self.assertTrue(mods & 0x0002)  # MOD_CONTROL
        self.assertTrue(mods & 0x0001)  # MOD_ALT
        self.assertEqual(vk, 0x20)      # VK_SPACE

    def test_helper_registers_and_cleans_up(self):
        from dastyar.winhelp import WindowsHelper

        opened, quit_called = [], []
        helper = WindowsHelper(
            tooltip="Dastyar test",
            on_open=lambda: opened.append(1),
            on_quit=lambda: quit_called.append(1),
            on_hotkey=lambda: opened.append(2),
            hotkey="ctrl+alt+f10",           # unlikely to clash with anything
        )
        helper.start()
        try:
            self.assertTrue(helper._hwnd, "message window was not created")
            # the icon must be visible in the notification area
            self.assertTrue(helper._icon_added, "tray icon could not be added")
        finally:
            helper.stop()
        self.assertFalse(helper._hwnd)

    def test_icon_file_is_valid_ico(self):
        from dastyar.config import bundled_path

        ico = bundled_path("assets", "icon.ico")
        self.assertTrue(ico.is_file())
        head = ico.read_bytes()[:6]
        self.assertEqual(head[:4], b"\x00\x00\x01\x00")   # ico magic
        self.assertGreater(int.from_bytes(head[4:6], "little"), 0)

    def test_dpi_awareness_can_be_set(self):
        from dastyar.winhelp import enable_dpi_awareness

        enable_dpi_awareness()   # must not raise on any Windows version


if __name__ == "__main__":
    unittest.main(verbosity=2)
