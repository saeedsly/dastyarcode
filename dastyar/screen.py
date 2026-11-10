"""Screen capture (Windows GDI via ctypes, macOS ``screencapture``, Linux tools).

No Pillow needed.  Output is PNG.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import IS_MAC, IS_WINDOWS, data_dir
from .utils import ensure_dir


class ScreenError(Exception):
    pass


# --------------------------------------------------------------------------- #
# PNG writing helper (8-bit RGB, no dependencies)
# --------------------------------------------------------------------------- #
def _write_png(path: Path, width: int, height: int, rgb_rows: bytes, stride: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        raw += rgb_rows[y * stride : y * stride + width * 3]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    path.write_bytes(out)


# --------------------------------------------------------------------------- #
def capture_screen(save_to: str = "", region: Optional[Tuple[int, int, int, int]] = None,
                   scale: float = 1.0) -> str:
    """Take a screenshot and return the PNG path.

    ``region`` is (left, top, width, height) in virtual-screen coordinates.
    ``scale`` downscales the image (useful to keep vision tokens small).
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if save_to:
        path = Path(os.path.expanduser(save_to))
        if path.is_dir() or not path.suffix:
            path = path / ("screenshot-%s.png" % stamp)
    else:
        path = ensure_dir(data_dir() / "screenshots") / ("screenshot-%s.png" % stamp)
    ensure_dir(path.parent)

    if IS_WINDOWS:
        _capture_windows(path, region, scale)
    elif IS_MAC:
        _capture_mac(path, region)
    else:
        _capture_linux(path)
    return str(path)


def _capture_windows(path: Path, region, scale: float) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.SetProcessDPIAware()

    if region:
        left, top, width, height = region
    else:
        left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        top = user32.GetSystemMetrics(77)
        width = user32.GetSystemMetrics(78)
        height = user32.GetSystemMetrics(79)

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old = gdi32.SelectObject(hdc_mem, bmp)
    gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 24
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    stride_src = ((width * 3 + 3) // 4) * 4
    buf = ctypes.create_string_buffer(stride_src * height)
    ok = gdi32.GetDIBits(hdc_mem, bmp, 0, height, buf, ctypes.byref(bmi), 0)
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    if not ok:
        raise ScreenError("گرفتن تصویر از صفحه ناموفق بود (GetDIBits).")

    data = bytes(buf)
    # convert BGR -> RGB (and optional downscale)
    rows = []
    step = 1
    if scale and 0 < scale < 1:
        step = int(round(1.0 / scale))
    for y in range(0, height, step):
        row = data[y * stride_src : y * stride_src + width * 3]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::3]
        rgb[1::3] = row[1::3]
        rgb[2::3] = row[0::3]
        if step > 1:
            rgb = bytearray(
                b for i in range(0, width, step) for b in rgb[i * 3 : i * 3 + 3]
            )
        rows.append(bytes(rgb))
    out_w = width if step == 1 else len(range(0, width, step))
    out_h = height if step == 1 else len(range(0, height, step))
    _write_png(path, out_w, out_h, b"".join(rows), out_w * 3)


def _capture_mac(path: Path, region) -> None:
    args = ["screencapture", "-x"]
    if region:
        args += ["-R", "%d,%d,%d,%d" % region]
    args.append(str(path))
    rc = subprocess.call(args)
    if rc != 0 or not path.exists():
        raise ScreenError("screencapture failed")


def _capture_linux(path: Path) -> None:
    for cmd in (
        ["gnome-screenshot", "-f", str(path)],
        ["scrot", "-o", str(path)],
        ["import", "-window", "root", str(path)],
        ["grim", str(path)],
    ):
        if subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            if path.exists():
                return
    raise ScreenError("هیچ ابزار عکس‌برداری روی لینوکس پیدا نشد (نصب کن: scrot یا imagemagick).")


def screenshot_info() -> Dict[str, str]:
    try:
        import ctypes

        if IS_WINDOWS:
            u = ctypes.windll.user32
            return {
                "width": str(u.GetSystemMetrics(0)),
                "height": str(u.GetSystemMetrics(1)),
                "virtual": "%sx%s @ %s,%s" % (
                    u.GetSystemMetrics(78), u.GetSystemMetrics(79),
                    u.GetSystemMetrics(76), u.GetSystemMetrics(77)),
            }
    except Exception:
        pass
    return {"width": "?", "height": "?", "virtual": "?"}
