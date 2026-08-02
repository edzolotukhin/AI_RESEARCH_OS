from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReportSection:
    """Structured section of a desk-research report."""

    id: str
    title: str
    content: str
    research_question_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    insight_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "research_question_refs": list(self.research_question_refs),
            "finding_refs": list(self.finding_refs),
            "insight_refs": list(self.insight_refs),
            "evidence_refs": list(self.evidence_refs),
            "citation_ids": list(self.citation_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReportSection:
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title", "")),
            content=str(payload.get("content", "")),
            research_question_refs=tuple(payload.get("research_question_refs", ())),
            finding_refs=tuple(payload.get("finding_refs", ())),
            insight_refs=tuple(payload.get("insight_refs", ())),
            evidence_refs=tuple(payload.get("evidence_refs", ())),
            citation_ids=tuple(payload.get("citation_ids", ())),
            metadata=dict(payload.get("metadata", {})),
        )
