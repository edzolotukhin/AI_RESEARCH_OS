from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.deduplication import compute_deduplication_key
from application.evidence.exceptions import (
    DuplicateEvidenceError,
    EvidenceExtractionError,
    UngroundedEvidenceError,
)
from application.evidence.grounding import verify_grounding
from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
from application.evidence.run_scoped_provenance import resolve_run_scoped_context
from application.ports.evidence_ports import EvidenceExtractor, EvidenceRepository
from application.ports.source_ports import SourceRepository
from application.sources.provenance_merge import is_successful_acquisition

from runtime.workflow_context import WorkflowContext

_MAX_DEDUP_RETRIES = 5


@dataclass(frozen=True)
class EvidenceExtractionSummary:
    evidence_ids: tuple[str, ...]
    sources_processed: int
    evidence_extracted: int
    extraction_failures: int
    sources_without_evidence: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ids": list(self.evidence_ids),
            "sources_processed": self.sources_processed,
            "evidence_extracted": self.evidence_extracted,
            "extraction_failures": self.extraction_failures,
            "sources_without_evidence": self.sources_without_evidence,
        }


class EvidenceExtractionService:
    """Extract grounded evidence from run-scoped acquired sources."""

    def __init__(
        self,
        *,
        evidence_extractor: EvidenceExtractor,
        evidence_repository: EvidenceRepository,
        source_repository: SourceRepository,
    ) -> None:
        self._evidence_extractor = evidence_extractor
        self._evidence_repository = evidence_repository
        self._source_repository = source_repository

    def extract_for_context(self, context: WorkflowContext) -> EvidenceExtractionSummary:
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        sources = self._eligible_sources(project_id, workflow_run_id)

        evidence_ids: list[str] = []
        extracted = 0
        failures = 0
        sources_without_evidence = 0

        for source in sources:
            source_ids, source_extracted, source_failures, had_none = (
                self._extract_from_source(
                    source=source,
                    design=design,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=design.id,
                )
            )
            evidence_ids.extend(source_ids)
            extracted += source_extracted
            failures += source_failures
            if had_none:
                sources_without_evidence += 1

        if extracted == 0:
            raise EvidenceExtractionError(
                f"No grounded evidence extracted for workflow run {workflow_run_id}",
            )

        return EvidenceExtractionSummary(
            evidence_ids=tuple(evidence_ids),
            sources_processed=len(sources),
            evidence_extracted=extracted,
            extraction_failures=failures,
            sources_without_evidence=sources_without_evidence,
        )

    def _resolve_design(self, context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise EvidenceExtractionError(
                "Workflow template is missing research_design_snapshot",
            )
        return template.research_design_snapshot

    def _eligible_sources(self, project_id: str, workflow_run_id: str) -> list[Source]:
        sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        return [
            source
            for source in sources
            if is_successful_acquisition(source.retrieval_status)
            and source.content_text.strip()
        ]

    def _extract_from_source(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> tuple[list[str], int, int, bool]:
        evidence_ids: list[str] = []
        extracted = 0
        failures = 0

        run_context = resolve_run_scoped_context(
            source=source,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )
        if not run_context.information_need_ids:
            return evidence_ids, extracted, failures, True

        try:
            candidates = self._evidence_extractor.extract(
                source=source,
                design=design,
                run_context=run_context,
            )
        except Exception:
            return evidence_ids, extracted, failures + 1, True

        if not candidates:
            return evidence_ids, extracted, failures, True

        for candidate in candidates:
            try:
                validated = validate_candidate_provenance(
                    candidate,
                    run_context=run_context,
                    design=design,
                )
                evidence_id = self._persist_candidate(
                    candidate=validated,
                    source=source,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                )
            except (UngroundedEvidenceError, InvalidProvenanceError):
                failures += 1
                continue
            evidence_ids.append(evidence_id)
            extracted += 1

        return evidence_ids, extracted, failures, extracted == 0

    def _persist_candidate(
        self,
        *,
        candidate,
        source: Source,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> str:
        metadata = dict(candidate.metadata or {})
        chunk_start = metadata.get("chunk_normalized_start")
        chunk_end = metadata.get("chunk_normalized_end")
        checksum = source.content_checksum or ""
        locator = verify_grounding(
            source_text=source.content_text,
            excerpt=candidate.source_excerpt,
            chunk_normalized_start=(
                int(chunk_start) if chunk_start is not None else None
            ),
            chunk_normalized_end=int(chunk_end) if chunk_end is not None else None,
        )
        deduplication_key = compute_deduplication_key(
            source_id=source.id,
            source_content_checksum=checksum,
            statement=candidate.statement,
            source_excerpt=candidate.source_excerpt,
            information_need_refs=candidate.information_need_refs,
        )
        existing = self._evidence_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id

        evidence = Evidence(
            id=str(uuid4()),
            project_id=project_id,
            source_id=source.id,
            source_content_checksum=checksum,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            research_question_refs=candidate.research_question_refs,
            information_need_refs=candidate.information_need_refs,
            evidence_type=EvidenceType(candidate.evidence_type),
            statement=candidate.statement,
            source_excerpt=candidate.source_excerpt,
            source_locator=locator.to_dict(),
            extraction_method=getattr(self._evidence_extractor, "method_name", "unknown"),
            confidence=candidate.confidence,
            quality_signals={
                "direct": candidate.direct,
                "source_retrieval_status": source.retrieval_status.value,
                "source_type": source.source_type,
            },
            deduplication_key=deduplication_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._evidence_repository.create(evidence)
                return evidence.id
            except DuplicateEvidenceError:
                existing = self._evidence_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise EvidenceExtractionError(
            f"Failed to resolve concurrent evidence persistence for run "
            f"{workflow_run_id}",
        )
