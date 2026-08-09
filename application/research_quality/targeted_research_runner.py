from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from domain.research_quality.targeted_research_request import TargetedResearchRequest

from runtime.workflow_context import WorkflowContext


@dataclass(frozen=True)
class TargetedResearchIterationResult:
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    queries_executed: int
    sources_acquired: int
    evidence_extracted: int
    extraction_attempted: bool = True
    budget_stop_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ids": list(self.source_ids),
            "evidence_ids": list(self.evidence_ids),
            "queries_executed": self.queries_executed,
            "sources_acquired": self.sources_acquired,
            "evidence_extracted": self.evidence_extracted,
            "extraction_attempted": self.extraction_attempted,
            "budget_stop_reason": self.budget_stop_reason,
        }


class TargetedResearchRunner(Protocol):
    """Runs one bounded targeted research iteration for a single gap."""

    def run(
        self,
        context: WorkflowContext,
        request: TargetedResearchRequest,
    ) -> TargetedResearchIterationResult:
        ...
