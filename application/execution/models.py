from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RunLease:
    run_id: str
    claimed_by: str
    lease_expires_at: datetime
    heartbeat_at: datetime
    version: int


@dataclass(frozen=True)
class ClaimResult:
    run_id: str
    version: int
