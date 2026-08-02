from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReviewIssueType(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_CITATION = "missing_citation"
    COVERAGE_GAP = "coverage_gap"
    CONTRADICTION = "contradiction"
    INCONSISTENT_ANALYSIS = "inconsistent_analysis"
    MISSING_LIMITATION = "missing_limitation"
    BRIEF_MISMATCH = "brief_mismatch"
    STRUCTURE_ISSUE = "structure_issue"


class ReviewIssueSeverity(str, Enum):
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True)
class ReviewIssue:
    id: str
    issue_type: ReviewIssueType
    severity: ReviewIssueSeverity
    message: str
    report_section_id: str | None = None
    finding_refs: tuple[str, ...] = ()
    insight_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    research_question_refs: tuple[str, ...] = ()
    suggested_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "issue_type": self.issue_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "report_section_id": self.report_section_id,
            "finding_refs": list(self.finding_refs),
            "insight_refs": list(self.insight_refs),
            "evidence_refs": list(self.evidence_refs),
            "source_refs": list(self.source_refs),
            "research_question_refs": list(self.research_question_refs),
            "suggested_action": self.suggested_action,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewIssue:
        return cls(
            id=str(payload["id"]),
            issue_type=ReviewIssueType(str(payload["issue_type"])),
            severity=ReviewIssueSeverity(str(payload["severity"])),
            message=str(payload.get("message", "")),
            report_section_id=payload.get("report_section_id"),
            finding_refs=tuple(payload.get("finding_refs", ())),
            insight_refs=tuple(payload.get("insight_refs", ())),
            evidence_refs=tuple(payload.get("evidence_refs", ())),
            source_refs=tuple(payload.get("source_refs", ())),
            research_question_refs=tuple(payload.get("research_question_refs", ())),
            suggested_action=str(payload.get("suggested_action", "")),
            metadata=dict(payload.get("metadata", {})),
        )
