from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from application.config import ApplicationConfig


class BackgroundExecutionMode(str, Enum):
    """Explicit background execution topology."""

    DISABLED = "disabled"
    EMBEDDED = "embedded"
    EXTERNAL = "external"


@dataclass(frozen=True)
class BackgroundExecutionCapability:
    """
    Background execution support for a configured topology.

    - http_submission: POST /research and POST /resume may return 202
    - in_process_worker: same process may drain runs (embedded/tests)
    - multi_process_worker: separate worker process shares durable state (PostgreSQL)
    """

    http_submission: bool
    in_process_worker: bool
    multi_process_worker: bool


def resolve_background_execution_mode(
    config: ApplicationConfig,
) -> BackgroundExecutionMode:
    if config.background_execution_mode is not None:
        raw = config.background_execution_mode.lower().strip()
        try:
            return BackgroundExecutionMode(raw)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported BACKGROUND_EXECUTION_MODE: {raw!r}. "
                "Expected one of: disabled, embedded, external."
            ) from exc

    if config.persistence_backend.lower() == "postgresql":
        return BackgroundExecutionMode.EXTERNAL

    return BackgroundExecutionMode.DISABLED


def resolve_background_execution_capability(
    config: ApplicationConfig,
    *,
    execution_port_available: bool,
) -> BackgroundExecutionCapability:
    unavailable = BackgroundExecutionCapability(
        http_submission=False,
        in_process_worker=False,
        multi_process_worker=False,
    )

    if not execution_port_available:
        return unavailable

    mode = resolve_background_execution_mode(config)
    backend = config.persistence_backend.lower()

    if mode == BackgroundExecutionMode.DISABLED:
        return unavailable

    if mode == BackgroundExecutionMode.EXTERNAL:
        if backend != "postgresql":
            return unavailable
        return BackgroundExecutionCapability(
            http_submission=True,
            in_process_worker=True,
            multi_process_worker=True,
        )

    if mode == BackgroundExecutionMode.EMBEDDED:
        if backend not in {"memory", "postgresql"}:
            return unavailable
        return BackgroundExecutionCapability(
            http_submission=True,
            in_process_worker=True,
            multi_process_worker=False,
        )

    return unavailable


def requires_http_background_submission(
    capability: BackgroundExecutionCapability,
) -> None:
    if not capability.http_submission:
        raise RuntimeError(
            "Durable background workflow execution is not enabled for the "
            "current persistence backend."
        )
