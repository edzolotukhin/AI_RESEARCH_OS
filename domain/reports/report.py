from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.reports.report_section import ReportSection


@dataclass
class Report:
    """Structured desk-research deliverable for one workflow run."""

    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    title: str
    language: str
    sections: tuple[ReportSection, ...]
    executive_summary: str
    limitations: tuple[str, ...]
    created_at: str
    generation_method: str
    finding_refs: tuple[str, ...]
    insight_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    citation_registry: dict[str, dict[str, Any]]
    deduplication_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "workflow_run_id": self.workflow_run_id,
            "research_design_id": self.research_design_id,
            "title": self.title,
            "language": self.language,
            "sections": [section.to_dict() for section in self.sections],
            "executive_summary": self.executive_summary,
            "limitations": list(self.limitations),
            "created_at": self.created_at,
            "generation_method": self.generation_method,
            "finding_refs": list(self.finding_refs),
            "insight_refs": list(self.insight_refs),
            "evidence_refs": list(self.evidence_refs),
            "citation_registry": dict(self.citation_registry),
            "deduplication_key": self.deduplication_key,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Report:
        return cls(
            id=str(payload["id"]),
            project_id=str(payload["project_id"]),
            workflow_run_id=str(payload["workflow_run_id"]),
            research_design_id=str(payload["research_design_id"]),
            title=str(payload.get("title", "")),
            language=str(payload.get("language", "")),
            sections=tuple(
                ReportSection.from_dict(item) for item in payload.get("sections", [])
            ),
            executive_summary=str(payload.get("executive_summary", "")),
            limitations=tuple(payload.get("limitations", ())),
            created_at=str(payload.get("created_at", "")),
            generation_method=str(payload.get("generation_method", "unknown")),
            finding_refs=tuple(payload.get("finding_refs", ())),
            insight_refs=tuple(payload.get("insight_refs", ())),
            evidence_refs=tuple(payload.get("evidence_refs", ())),
            citation_registry=dict(payload.get("citation_registry", {})),
            deduplication_key=str(payload.get("deduplication_key", "")),
            metadata=dict(payload.get("metadata", {})),
            version=int(payload.get("version", 0)),
        )
