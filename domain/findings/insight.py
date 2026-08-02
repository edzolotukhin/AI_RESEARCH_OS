from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Insight:
    """Interpretation of Findings in the context of the research objective."""

    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    statement: str
    implication: str
    finding_refs: tuple[str, ...]
    created_at: str
    research_question_refs: tuple[str, ...] = ()
    confidence: float | None = None
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
            "statement": self.statement,
            "implication": self.implication,
            "finding_refs": list(self.finding_refs),
            "confidence": self.confidence,
            "deduplication_key": self.deduplication_key,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Insight:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            research_question_refs=tuple(
                str(item) for item in payload.get("research_question_refs", [])
            ),
            statement=str(payload.get("statement", "")),
            implication=str(payload.get("implication", "")),
            finding_refs=tuple(str(item) for item in payload.get("finding_refs", [])),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            deduplication_key=str(payload.get("deduplication_key", "")),
            created_at=str(payload["created_at"]),
            metadata=dict(payload.get("metadata") or {}),
            version=int(payload.get("version", 0)),
        )
