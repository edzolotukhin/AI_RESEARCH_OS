from __future__ import annotations

from typing import Protocol


class RunQueue(Protocol):
    """
    Advisory notification channel for runnable workflow runs.

    PostgreSQL run state and leases remain authoritative; a lost notification
    must not lose work.
    """

    def notify_runnable(self, run_id: str) -> None:
        """Signal that a run may be claimed. Failures must not roll back durability."""
        ...
