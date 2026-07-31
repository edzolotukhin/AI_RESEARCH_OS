from __future__ import annotations

from typing import Protocol

from application.persistence.records import KnowledgeItem


class KnowledgeRepository(Protocol):
    """Persistence port for project-scoped knowledge items."""

    def save(
        self,
        item: KnowledgeItem,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Persist a knowledge item. Returns the new record version."""
        ...

    def get_by_id(self, item_id: str) -> KnowledgeItem | None:
        """Load a knowledge item by identifier."""
        ...

    def list_for_project(self, project_id: str) -> list[KnowledgeItem]:
        """List knowledge items for a project."""
        ...

    def delete(self, item_id: str) -> None:
        """Remove a knowledge item."""
        ...
