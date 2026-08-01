from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LeaseConfig:
    """Bounded lease and heartbeat timing for background workers."""

    lease_duration_seconds: float = 30.0
    heartbeat_interval_seconds: float = 10.0
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> LeaseConfig:
        return cls(
            lease_duration_seconds=float(
                os.environ.get("WORKER_LEASE_DURATION_SECONDS", "30"),
            ),
            heartbeat_interval_seconds=float(
                os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "10"),
            ),
            poll_interval_seconds=float(
                os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "1"),
            ),
        )
