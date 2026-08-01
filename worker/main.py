from __future__ import annotations

import sys

from application.composition_root import create_application_container


def main() -> int:
    container = create_application_container()
    if (
        container.background_execution is None
        or not container.background_execution.multi_process_worker
    ):
        print(
            "worker startup refused: multi_process_background_execution_unavailable",
            file=sys.stderr,
        )
        container.shutdown()
        return 1
    from worker.loop import WorkerLoop, install_signal_handlers

    loop = WorkerLoop(container)
    install_signal_handlers(loop)
    try:
        loop.run()
    finally:
        container.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
