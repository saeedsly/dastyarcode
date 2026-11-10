"""Entry point: ``python -m dastyar`` or ``dastyar`` console script."""
import sys

from .config import enable_console_safety

# must happen before anything tries to print (windowed exe has no console)
enable_console_safety()

from .cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
