from __future__ import annotations

import os

from application.composition_root import create_application_container
from worker.logging_config import configure_worker_logging

logger = configure_worker_logging()


def main() -> int:
    container = create_application_container()
    if (
        container.background_execution is None
        or not container.background_execution.multi_process_worker
    ):
        logger.error(
            "worker_startup_refused reason=multi_process_background_execution_unavailable "
            "persistence_backend=%s",
            container.config.persistence_backend,
        )
        container.shutdown()
        return 1
    from worker.loop import WorkerLoop, install_signal_handlers

    worker_id = os.environ.get("WORKER_ID") or None
    loop = WorkerLoop(container, worker_id=worker_id)
    install_signal_handlers(loop)
    try:
        loop.run()
    except Exception:
        logger.exception(
            "worker_loop_fatal worker_id=%s persistence_backend=%s",
            loop.worker_id,
            container.config.persistence_backend,
        )
        return 1
    finally:
        container.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
