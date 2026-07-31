from __future__ import annotations

from application.config import ApplicationConfig


def supports_durable_workflow_execution(config: ApplicationConfig) -> bool:
    if config.durable_workflow_execution is not None:
        return config.durable_workflow_execution

    return config.persistence_backend in {"memory", "postgresql"}
