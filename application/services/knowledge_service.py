"""
Knowledge item persistence service.

KnowledgeItem is a persistence-boundary record. Vector search, embeddings,
and document parsing are out of scope for PF-02.5.
"""

from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import KnowledgeItem
from application.ports.knowledge_repository import KnowledgeRepository


class KnowledgeService:
    """Coordinates project-scoped knowledge item persistence use cases."""

    def __init__(self, *, knowledge_repository: KnowledgeRepository) -> None:
        self._knowledge_repository = knowledge_repository

    def save_knowledge_item(
        self,
        item: KnowledgeItem,
        *,
        expected_version: int | None = None,
    ) -> int:
        return self._knowledge_repository.save(
            item,
            expected_version=expected_version,
        )

    def get_knowledge_item(self, item_id: str) -> KnowledgeItem:
        item = self._knowledge_repository.get_by_id(item_id)
        if item is None:
            raise EntityNotFoundError(f"KnowledgeItem not found: {item_id}")
        return item

    def list_knowledge_for_project(
        self,
        project_id: str,
    ) -> list[KnowledgeItem]:
        return self._knowledge_repository.list_for_project(project_id)

    def delete_knowledge_item(self, item_id: str) -> None:
        if self._knowledge_repository.get_by_id(item_id) is None:
            raise EntityNotFoundError(f"KnowledgeItem not found: {item_id}")
        self._knowledge_repository.delete(item_id)
