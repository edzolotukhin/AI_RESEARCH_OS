from __future__ import annotations

from datetime import datetime, timezone

from application.persistence.exceptions import DuplicateEntityError
from application.persistence.records import ApiKeyRecord
from application.ports.api_key_repository import ApiKeyRepository


class InMemoryApiKeyRepository(ApiKeyRepository):
    def __init__(self) -> None:
        self._records: dict[str, ApiKeyRecord] = {}

    def create(self, record: ApiKeyRecord) -> None:
        if record.id in self._records:
            raise DuplicateEntityError(f"API key already exists: {record.id}")
        self._records[record.id] = record

    def get_by_id(self, key_id: str) -> ApiKeyRecord | None:
        return self._records.get(key_id)

    def mark_used(self, key_id: str, *, used_at: datetime) -> None:
        existing = self._records.get(key_id)
        if existing is None:
            return
        self._records[key_id] = ApiKeyRecord(
            id=existing.id,
            principal_id=existing.principal_id,
            name=existing.name,
            key_prefix=existing.key_prefix,
            key_hash=existing.key_hash,
            is_active=existing.is_active,
            created_at=existing.created_at,
            last_used_at=used_at,
            revoked_at=existing.revoked_at,
        )

    def revoke(self, key_id: str, *, revoked_at: datetime) -> None:
        existing = self._records.get(key_id)
        if existing is None:
            return
        self._records[key_id] = ApiKeyRecord(
            id=existing.id,
            principal_id=existing.principal_id,
            name=existing.name,
            key_prefix=existing.key_prefix,
            key_hash=existing.key_hash,
            is_active=False,
            created_at=existing.created_at,
            last_used_at=existing.last_used_at,
            revoked_at=revoked_at,
        )
