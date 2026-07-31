from __future__ import annotations

from sqlalchemy import delete, select

from application.persistence.records import KnowledgeItem
from application.ports.knowledge_repository import KnowledgeRepository
from infrastructure.persistence.postgresql.concurrency import atomic_update_version
from infrastructure.persistence.postgresql.mappers.knowledge_mapper import (
    knowledge_from_model,
    knowledge_to_model,
    knowledge_to_update_values,
)
from infrastructure.persistence.postgresql.models.knowledge_model import (
    KnowledgeItemModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLKnowledgeRepository:
    """PostgreSQL adapter for KnowledgeRepository."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def save(
        self,
        item: KnowledgeItem,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            existing = session.get(KnowledgeItemModel, item.id)
            if existing is None:
                session.add(knowledge_to_model(item, version=1))
                item.version = 1
                return 1

            new_version = atomic_update_version(
                session,
                KnowledgeItemModel,
                item.id,
                expected_version=expected_version,
                values=knowledge_to_update_values(item),
            )
            item.version = new_version
            return new_version

    def get_by_id(self, item_id: str) -> KnowledgeItem | None:
        with self._session_factory.session() as session:
            model = session.get(KnowledgeItemModel, item_id)
            if model is None:
                return None
            return knowledge_from_model(model)

    def list_for_project(self, project_id: str) -> list[KnowledgeItem]:
        with self._session_factory.session() as session:
            statement = (
                select(KnowledgeItemModel)
                .where(KnowledgeItemModel.project_id == project_id)
                .order_by(KnowledgeItemModel.id)
            )
            return [
                knowledge_from_model(model)
                for model in session.scalars(statement).all()
            ]

    def delete(self, item_id: str) -> None:
        with self._session_factory.session() as session:
            session.execute(
                delete(KnowledgeItemModel).where(KnowledgeItemModel.id == item_id)
            )
