from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.findings.finding_type import FindingType


@dataclass
class Finding:
    """Analytical conclusion supported by durable Evidence records."""

    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    statement: str
    rationale: str
    evidence_refs: tuple[str, ...]
    created_at: str
    research_question_refs: tuple[str, ...] = ()
    information_need_refs: tuple[str, ...] = ()
    finding_type: FindingType = FindingType.SYNTHESIS
    confidence: float | None = None
    analysis_method: str = "unknown"
    deduplication_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "workflow_run_id": self.workflow_run_id,
            "research_design_id": self.research_design_id,
            "research_question_refs": list(self.research_question_refs),
            "information_need_refs": list(self.information_need_refs),
            "statement": self.statement,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "finding_type": self.finding_type.value,
            "confidence": self.confidence,
            "analysis_method": self.analysis_method,
            "deduplication_key": self.deduplication_key,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Finding:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            research_question_refs=tuple(
                str(item) for item in payload.get("research_question_refs", [])
            ),
            information_need_refs=tuple(
                str(item) for item in payload.get("information_need_refs", [])
            ),
            statement=str(payload.get("statement", "")),
            rationale=str(payload.get("rationale", "")),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", [])),
            finding_type=FindingType(
                str(payload.get("finding_type", FindingType.SYNTHESIS.value)),
            ),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            analysis_method=str(payload.get("analysis_method", "unknown")),
            deduplication_key=str(payload.get("deduplication_key", "")),
            created_at=str(payload["created_at"]),
            metadata=dict(payload.get("metadata") or {}),
            version=int(payload.get("version", 0)),
        )
