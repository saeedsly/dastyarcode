"""Entry point used by the compiled Windows exe.

PyInstaller executes this file as a *script* (``__main__``), not as part of the
``dastyar`` package, so relative imports would fail.  We therefore import the
package by name, which works in every situation:

  * ``Dastyar.exe``                  -> desktop app (window + tray + hotkey)
  * ``Dastyar.exe doctor``           -> health check
  * ``Dastyar.exe serve --port 9000``-> plain web server
"""
import sys

# The windowed exe has no console: give print() a safe sink before anything
# else runs, otherwise the first log line would kill the app.
from dastyar.config import enable_console_safety

enable_console_safety()


def main() -> int:
    from dastyar.cli import main as cli_main

    argv = sys.argv[1:]
    if not argv:
        # double click: nothing to parse -> desktop app with tray + hotkey
        return cli_main(["run"])
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
