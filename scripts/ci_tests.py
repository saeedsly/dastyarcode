#!/usr/bin/env python3
"""Run the test suite and, on CI, emit GitHub annotations for every failure.

Why a custom runner: when a job fails the raw log is not always reachable, but
annotations are.  Printing ``::error::`` lines means the exact assertion text
shows up on the pull request / run page.

Locally this behaves like ``python -m unittest discover -s tests -v``.
"""
from __future__ import annotations

import os
import sys
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ON_CI = os.environ.get("GITHUB_ACTIONS") == "true"


def _escape(text: str) -> str:
    # GitHub annotation payloads must not contain raw newlines
    return text.replace("\r", "").replace("\n", " | ").replace("%", "%25")


def _err(message: str) -> None:
    print("::error::" + _escape(message))


class AnnouncingResult(unittest.TextTestResult):
    """TextTestResult that mirrors failures into CI annotations."""

    def addFailure(self, test, err):  # noqa: N802 (unittest API)
        super().addFailure(test, err)
        if ON_CI:
            _err("FAIL %s -> %s" % (test.id(), err[1]))

    def addError(self, test, err):  # noqa: N802
        super().addError(test, err)
        if ON_CI:
            _err("ERROR %s -> %s" % (test.id(), err[1]))

    def addSkip(self, test, reason):  # noqa: N802
        super().addSkip(test, reason)
        if ON_CI:
            print("::warning::SKIP %s -> %s" % (test.id(), _escape(reason)))


def main() -> int:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    pattern = "test_*.py"
    for arg in sys.argv[1:]:
        if arg.startswith("--pattern="):
            pattern = arg.split("=", 1)[1]

    print("python %s on %s" % (sys.version.split()[0], sys.platform))
    print("root: %s" % ROOT)
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), pattern=pattern)
    runner = unittest.TextTestRunner(
        verbosity=2 if verbose else 1, resultclass=AnnouncingResult, buffer=False
    )
    result = runner.run(suite)

    if result.errors or result.failures:
        print("\n--- failure details ---")
        for test, tb in list(result.errors) + list(result.failures):
            print("\n### %s" % test.id())
            print("".join(traceback.format_exception(*tb)))

    print(
        "\nran %d tests: %d ok, %d failures, %d errors, %d skipped"
        % (
            result.testsRun,
            result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
            len(result.failures),
            len(result.errors),
            len(result.skipped),
        )
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
