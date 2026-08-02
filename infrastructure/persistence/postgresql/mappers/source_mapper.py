from __future__ import annotations

from datetime import datetime

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from infrastructure.persistence.postgresql.models.source_model import SourceModel


def _parse_datetime(value: str | None):
    if value is None or value == "":
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def source_to_model(source: Source, *, version: int) -> SourceModel:
    return SourceModel(
        id=source.id,
        project_id=source.project_id,
        url=source.url,
        canonical_url=source.canonical_url,
        title=source.title,
        publisher=source.publisher or None,
        author=source.author or None,
        published_at=_parse_datetime(source.published_at),
        retrieved_at=_parse_datetime(source.retrieved_at),
        source_type=source.source_type,
        language=source.language or None,
        content_type=source.content_type or None,
        query_refs=list(source.query_refs),
        research_question_refs=list(source.research_question_refs),
        information_need_refs=list(source.information_need_refs),
        workflow_run_refs=list(source.workflow_run_refs),
        research_design_refs=list(source.research_design_refs),
        retrieval_status=source.retrieval_status.value,
        content_text=source.content_text or None,
        content_checksum=source.content_checksum or None,
        metadata_json=dict(source.metadata),
        version=version,
    )


def source_to_update_values(source: Source) -> dict:
    return {
        "url": source.url,
        "canonical_url": source.canonical_url,
        "title": source.title,
        "publisher": source.publisher or None,
        "author": source.author or None,
        "published_at": _parse_datetime(source.published_at),
        "retrieved_at": _parse_datetime(source.retrieved_at),
        "source_type": source.source_type,
        "language": source.language or None,
        "content_type": source.content_type or None,
        "query_refs": list(source.query_refs),
        "research_question_refs": list(source.research_question_refs),
        "information_need_refs": list(source.information_need_refs),
        "workflow_run_refs": list(source.workflow_run_refs),
        "research_design_refs": list(source.research_design_refs),
        "retrieval_status": source.retrieval_status.value,
        "content_text": source.content_text or None,
        "content_checksum": source.content_checksum or None,
        "metadata_json": dict(source.metadata),
    }


def source_from_model(model: SourceModel) -> Source:
    return Source(
        id=model.id,
        project_id=model.project_id,
        url=model.url,
        canonical_url=model.canonical_url,
        title=model.title,
        publisher=model.publisher or "",
        author=model.author or "",
        published_at=model.published_at.isoformat() if model.published_at else None,
        retrieved_at=model.retrieved_at.isoformat(),
        source_type=model.source_type,
        language=model.language or "",
        content_type=model.content_type or "",
        query_refs=tuple(str(item) for item in (model.query_refs or [])),
        research_question_refs=tuple(
            str(item) for item in (model.research_question_refs or [])
        ),
        information_need_refs=tuple(
            str(item) for item in (model.information_need_refs or [])
        ),
        workflow_run_refs=tuple(str(item) for item in (model.workflow_run_refs or [])),
        research_design_refs=tuple(
            str(item) for item in (model.research_design_refs or [])
        ),
        retrieval_status=RetrievalStatus(model.retrieval_status),
        content_text=model.content_text or "",
        content_checksum=model.content_checksum or "",
        metadata=dict(model.metadata_json or {}),
        version=model.version,
    )
