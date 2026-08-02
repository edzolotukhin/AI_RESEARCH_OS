from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.sources.retrieval_status import RetrievalStatus


@dataclass
class Source:
    """Durable acquired research source with stable provenance."""

    id: str
    project_id: str
    url: str
    canonical_url: str
    title: str
    retrieved_at: str
    source_type: str = "web"
    publisher: str = ""
    author: str = ""
    published_at: str | None = None
    language: str = ""
    content_type: str = ""
    query_refs: tuple[str, ...] = ()
    research_question_refs: tuple[str, ...] = ()
    information_need_refs: tuple[str, ...] = ()
    workflow_run_refs: tuple[str, ...] = ()
    research_design_refs: tuple[str, ...] = ()
    retrieval_status: RetrievalStatus = RetrievalStatus.ACQUIRED
    content_text: str = ""
    content_checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "publisher": self.publisher,
            "author": self.author,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "source_type": self.source_type,
            "language": self.language,
            "content_type": self.content_type,
            "query_refs": list(self.query_refs),
            "research_question_refs": list(self.research_question_refs),
            "information_need_refs": list(self.information_need_refs),
            "workflow_run_refs": list(self.workflow_run_refs),
            "research_design_refs": list(self.research_design_refs),
            "retrieval_status": self.retrieval_status.value,
            "content_text": self.content_text,
            "content_checksum": self.content_checksum,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Source:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            url=str(payload["url"]),
            canonical_url=str(payload["canonical_url"]),
            title=str(payload.get("title", "")),
            publisher=str(payload.get("publisher", "")),
            author=str(payload.get("author", "")),
            published_at=(
                str(payload["published_at"])
                if payload.get("published_at") is not None
                else None
            ),
            retrieved_at=str(payload["retrieved_at"]),
            source_type=str(payload.get("source_type", "web") or "web"),
            language=str(payload.get("language", "")),
            content_type=str(payload.get("content_type", "")),
            query_refs=tuple(str(item) for item in payload.get("query_refs", [])),
            research_question_refs=tuple(
                str(item) for item in payload.get("research_question_refs", [])
            ),
            information_need_refs=tuple(
                str(item) for item in payload.get("information_need_refs", [])
            ),
            workflow_run_refs=tuple(
                str(item) for item in payload.get("workflow_run_refs", [])
            ),
            research_design_refs=tuple(
                str(item) for item in payload.get("research_design_refs", [])
            ),
            retrieval_status=RetrievalStatus(
                str(payload.get("retrieval_status", RetrievalStatus.ACQUIRED.value)),
            ),
            content_text=str(payload.get("content_text", "")),
            content_checksum=str(payload.get("content_checksum", "")),
            metadata=dict(payload.get("metadata") or {}),
            version=int(payload.get("version", 0)),
        )
