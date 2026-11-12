# دستیار / Dastyar — build a standalone .exe package (run on Windows)

This produces a **single folder you can zip and give to anyone**: no Python,
no admin rights, works on Windows 7 SP1 → 11.

```bat
cd installer
build_exe.cmd
```

Output: `dist\Dastyar\Dastyar.exe` (+ `dist\Dastyar-win64.zip`).

How it works
------------
1. installs PyInstaller into a throw-away virtual environment
2. bundles the whole `dastyar` package (web UI, fonts, icons all included)
3. produces a windowed exe with the app icon and version info
4. zips the folder

You can also run PyInstaller by hand:

```bat
python -m pip install pyinstaller
pyinstaller --noconfirm --clean dastyar.spec
```

Notes
-----
* The exe still talks to whatever LLM you configure (API key) or runs the
  offline demo mode, so it needs no bundled model.
* For voice, users can run `Dastyar.exe doctor` and install `edge-tts`
  with the built-in package manager button (or simply keep using the Windows
  SAPI voice which is always present).
* Code signing is optional; unsigned exes trigger SmartScreen on first run
  (users click "More info → Run anyway").
