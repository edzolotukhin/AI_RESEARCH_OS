from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from application.persistence.exceptions import DuplicateEntityError
from application.persistence.records import ApiKeyRecord
from application.ports.api_key_repository import ApiKeyRepository
from infrastructure.persistence.postgresql.models.api_key_model import ApiKeyModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


def _to_record(model: ApiKeyModel) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=model.id,
        principal_id=model.principal_id,
        name=model.name,
        key_prefix=model.key_prefix,
        key_hash=model.key_hash,
        is_active=model.is_active,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        revoked_at=model.revoked_at,
    )


class PostgreSQLApiKeyRepository(ApiKeyRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, record: ApiKeyRecord) -> None:
        with self._session_factory.session() as session:
            existing = session.get(ApiKeyModel, record.id)
            if existing is not None:
                raise DuplicateEntityError(f"API key already exists: {record.id}")
            session.add(
                ApiKeyModel(
                    id=record.id,
                    principal_id=record.principal_id,
                    name=record.name,
                    key_prefix=record.key_prefix,
                    key_hash=record.key_hash,
                    is_active=record.is_active,
                    created_at=record.created_at,
                    last_used_at=record.last_used_at,
                    revoked_at=record.revoked_at,
                )
            )

    def get_by_id(self, key_id: str) -> ApiKeyRecord | None:
        with self._session_factory.session() as session:
            model = session.get(ApiKeyModel, key_id)
            if model is None:
                return None
            return _to_record(model)

    def mark_used(self, key_id: str, *, used_at: datetime) -> None:
        with self._session_factory.session() as session:
            session.execute(
                update(ApiKeyModel)
                .where(ApiKeyModel.id == key_id)
                .values(last_used_at=used_at)
            )

    def revoke(self, key_id: str, *, revoked_at: datetime) -> None:
        with self._session_factory.session() as session:
            session.execute(
                update(ApiKeyModel)
                .where(ApiKeyModel.id == key_id)
                .values(
                    is_active=False,
                    revoked_at=revoked_at,
                )
            )
