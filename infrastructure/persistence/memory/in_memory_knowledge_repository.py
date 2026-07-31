from __future__ import annotations

import copy

from application.persistence.exceptions import ConcurrentModificationError
from application.persistence.records import KnowledgeItem
from application.ports.knowledge_repository import KnowledgeRepository


class InMemoryKnowledgeRepository:
    """In-memory KnowledgeRepository adapter."""

    def __init__(self) -> None:
        self._items: dict[str, KnowledgeItem] = {}
        self._versions: dict[str, int] = {}
        self._project_index: dict[str, list[str]] = {}

    def save(
        self,
        item: KnowledgeItem,
        *,
        expected_version: int | None = None,
    ) -> int:
        current_version = self._versions.get(item.id, 0)
        if (
            expected_version is not None
            and expected_version != current_version
        ):
            raise ConcurrentModificationError(
                f"KnowledgeItem {item.id} version mismatch: "
                f"expected {expected_version}, found {current_version}."
            )

        self._items[item.id] = copy.deepcopy(item)
        project_items = self._project_index.setdefault(item.project_id, [])
        if item.id not in project_items:
            project_items.append(item.id)

        new_version = current_version + 1
        self._versions[item.id] = new_version
        item.version = new_version
        return new_version

    def get_by_id(self, item_id: str) -> KnowledgeItem | None:
        item = self._items.get(item_id)
        if item is None:
            return None
        return copy.deepcopy(item)

    def list_for_project(self, project_id: str) -> list[KnowledgeItem]:
        item_ids = self._project_index.get(project_id, [])
        return [
            copy.deepcopy(self._items[item_id])
            for item_id in item_ids
            if item_id in self._items
        ]

    def delete(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        self._versions.pop(item_id, None)
        if item is None:
            return

        project_items = self._project_index.get(item.project_id, [])
        if item_id in project_items:
            project_items.remove(item_id)
