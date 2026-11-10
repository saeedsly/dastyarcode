"""Entry point used by the compiled Windows exe.

When the user double-clicks Dastyar.exe we want the desktop app (window + tray
icon).  Passing a subcommand still works exactly like the CLI, so
``Dastyar.exe doctor`` and ``Dastyar.exe serve --port 9000`` behave normally.
"""
import sys

from .config import enable_console_safety

enable_console_safety()


def main() -> int:
    from .cli import main as cli_main

    argv = sys.argv[1:]
    if not argv:
        # double click: nothing to parse -> desktop app with tray + hotkey
        return cli_main(["run"])
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
