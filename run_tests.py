"""
Standard test entrypoint for AI Research OS.

Usage from repository root:
    python run_tests.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(project_root / "tests"),
        pattern="test_*.py",
        top_level_dir=str(project_root),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
