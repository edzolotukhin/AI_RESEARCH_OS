from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from application.evidence.run_scoped_provenance import RunScopedSourceContext
from domain.evidence.evidence import Evidence
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source


@dataclass(frozen=True)
class EvidenceCandidate:
    """Structured extraction output before authoritative provenance is attached."""

    statement: str
    source_excerpt: str
    evidence_type: str
    research_question_refs: tuple[str, ...]
    information_need_refs: tuple[str, ...]
    confidence: float | None = None
    direct: bool = True
    metadata: dict[str, Any] | None = None


class EvidenceExtractor(Protocol):
    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        ...


class EvidenceRepository(Protocol):
    def create(self, evidence: Evidence) -> int:
        ...

    def get_by_id(self, evidence_id: str) -> Evidence | None:
        ...

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Evidence | None:
        ...

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        source_id: str | None = None,
    ) -> list[Evidence]:
        ...
