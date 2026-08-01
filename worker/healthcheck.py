from __future__ import annotations

import sys

from application.composition_root import create_application_container


def main() -> int:
    container = create_application_container()
    try:
        if (
            container.background_execution is None
            or not container.background_execution.multi_process_worker
        ):
            print(
                "worker not ready: multi_process_background_execution_unavailable",
                file=sys.stderr,
            )
            return 1
        ready, reason = container.check_readiness()
        if not ready:
            print(f"worker not ready: {reason}", file=sys.stderr)
            return 1
        return 0
    finally:
        container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
