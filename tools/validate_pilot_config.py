from __future__ import annotations

import argparse
import os
from pathlib import Path

from application.production_config import ProductionConfigurationError, validate_production_environment


def validate_paths() -> None:
    for name in ("QUANTITATIVE_PROTECTED_STORAGE_ROOT", "PROJECTS_ROOT"):
        value = os.environ.get(name, "").strip()
        if not value:
            raise ProductionConfigurationError(f"{name} is required")
        path = Path(value)
        if not path.exists() or not path.is_dir():
            raise ProductionConfigurationError(f"{name} must reference an existing directory")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate non-secret pilot readiness")
    parser.add_argument("--check-paths", action="store_true")
    args = parser.parse_args()
    try:
        validate_production_environment()
        if args.check_paths:
            validate_paths()
    except ProductionConfigurationError as exc:
        print(f"pilot configuration invalid: {exc}")
        return 2
    print("pilot configuration valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
