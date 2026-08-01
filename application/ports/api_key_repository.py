from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from application.persistence.records import ApiKeyRecord


class ApiKeyRepository(ABC):
    """Durable API key registry."""

    @abstractmethod
    def create(self, record: ApiKeyRecord) -> None:
        """Persist a new API key record."""

    @abstractmethod
    def get_by_id(self, key_id: str) -> ApiKeyRecord | None:
        """Load an API key by public identifier."""

    @abstractmethod
    def mark_used(self, key_id: str, *, used_at: datetime) -> None:
        """Record successful authentication timestamp."""

    @abstractmethod
    def revoke(self, key_id: str, *, revoked_at: datetime) -> None:
        """Revoke an API key."""
