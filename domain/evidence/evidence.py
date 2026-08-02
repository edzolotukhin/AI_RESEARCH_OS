from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.evidence.evidence_type import EvidenceType


@dataclass
class Evidence:
    """Durable research evidence extracted from an acquired Source snapshot."""

    id: str
    project_id: str
    source_id: str
    source_content_checksum: str
    workflow_run_id: str
    research_design_id: str
    statement: str
    source_excerpt: str
    created_at: str
    evidence_type: EvidenceType = EvidenceType.DIRECT_EXCERPT
    research_question_refs: tuple[str, ...] = ()
    information_need_refs: tuple[str, ...] = ()
    source_locator: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = "deterministic"
    confidence: float | None = None
    quality_signals: dict[str, Any] = field(default_factory=dict)
    deduplication_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "source_content_checksum": self.source_content_checksum,
            "workflow_run_id": self.workflow_run_id,
            "research_design_id": self.research_design_id,
            "research_question_refs": list(self.research_question_refs),
            "information_need_refs": list(self.information_need_refs),
            "evidence_type": self.evidence_type.value,
            "statement": self.statement,
            "source_excerpt": self.source_excerpt,
            "source_locator": dict(self.source_locator),
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "quality_signals": dict(self.quality_signals),
            "deduplication_key": self.deduplication_key,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Evidence:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            source_id=str(payload["source_id"]),
            source_content_checksum=str(payload["source_content_checksum"]),
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            research_question_refs=tuple(
                str(item) for item in payload.get("research_question_refs", [])
            ),
            information_need_refs=tuple(
                str(item) for item in payload.get("information_need_refs", [])
            ),
            evidence_type=EvidenceType(
                str(payload.get("evidence_type", EvidenceType.DIRECT_EXCERPT.value)),
            ),
            statement=str(payload.get("statement", "")),
            source_excerpt=str(payload.get("source_excerpt", "")),
            source_locator=dict(payload.get("source_locator") or {}),
            extraction_method=str(payload.get("extraction_method", "deterministic")),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            quality_signals=dict(payload.get("quality_signals") or {}),
            deduplication_key=str(payload.get("deduplication_key", "")),
            created_at=str(payload["created_at"]),
            metadata=dict(payload.get("metadata") or {}),
            version=int(payload.get("version", 0)),
        )
