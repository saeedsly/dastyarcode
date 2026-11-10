# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-folder build of Dastyar (fast start, all assets)."""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()  # noqa: F821
sys.path.insert(0, str(ROOT))

block_cipher = None

datas = [
    (str(ROOT / "dastyar" / "web"), "dastyar/web"),
    (str(ROOT / "dastyar" / "assets"), "dastyar/assets"),
]

hiddenimports = [
    "dastyar.tools.files", "dastyar.tools.apps", "dastyar.tools.system",
    "dastyar.tools.net", "dastyar.tools.websearch", "dastyar.tools.browser",
    "dastyar.tools.vision", "dastyar.tools.office", "dastyar.tools.docs",
    "dastyar.tools.media", "dastyar.tools.speak", "dastyar.tools.code_runner",
    "dastyar.tools.windows_ui", "dastyar.tools.registry", "dastyar.tools.schedule",
    "dastyar.tools.memory", "dastyar.tools.notes", "dastyar.tools.dev",
    "dastyar.tools.fun", "dastyar.tools.pdfkit",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "dastyar" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "pandas", "matplotlib", "PIL", "test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dastyar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "dastyar" / "assets" / "icon.ico"),
    version=str(ROOT / "installer" / "version_info.txt"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Dastyar",
)
