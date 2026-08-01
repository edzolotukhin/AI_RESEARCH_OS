from __future__ import annotations


class NoOpRunQueue:
    """PostgreSQL polling worker model — notifications are optional."""

    def notify_runnable(self, run_id: str) -> None:
        return None
