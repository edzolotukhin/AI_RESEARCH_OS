from __future__ import annotations

from application.persistence.records import KnowledgeItem
from infrastructure.persistence.postgresql.models.knowledge_model import (
    KnowledgeItemModel,
)


def knowledge_to_model(item: KnowledgeItem, *, version: int) -> KnowledgeItemModel:
    return KnowledgeItemModel(
        id=item.id,
        project_id=item.project_id,
        title=item.title,
        content=item.content,
        version=version,
    )


def knowledge_to_update_values(item: KnowledgeItem) -> dict:
    return {
        "project_id": item.project_id,
        "title": item.title,
        "content": item.content,
    }


def knowledge_from_model(model: KnowledgeItemModel) -> KnowledgeItem:
    return KnowledgeItem(
        id=model.id,
        project_id=model.project_id,
        title=model.title,
        content=model.content,
        version=model.version,
    )
