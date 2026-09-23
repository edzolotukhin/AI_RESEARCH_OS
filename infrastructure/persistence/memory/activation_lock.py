from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Iterator


class InMemoryActivationCoordinator:
    """Serialize in-process activation retries; memory is not durable storage."""

    transactional = False

    def __init__(self) -> None:
        self._lock = RLock()

    @contextmanager
    def activation(self, project_id: str) -> Iterator[None]:
        with self._lock:
            yield

    def defer_until_commit(self, callback) -> bool:
        return False
