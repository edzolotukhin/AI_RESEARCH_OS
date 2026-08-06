from __future__ import annotations

from datetime import datetime, timezone

from application.ports.evidence_ports import EvidenceRepository
from application.ports.source_ports import SourceRepository
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from runtime.workflow_context import WorkflowContext


class DeterministicTargetedResearchRunner:
    """
    Offline/test targeted research runner without Search or LLM.

    Not used as a production fallback; inject via ApplicationOverrides in tests.
    """

    def __init__(
        self,
        *,
        source_repository: SourceRepository,
        evidence_repository: EvidenceRepository,
        on_run: Callable[[WorkflowContext, TargetedResearchRequest], None] | None = None,
    ) -> None:
        self._source_repository = source_repository
        self._evidence_repository = evidence_repository
        self._on_run = on_run

    def run(
        self,
        context: WorkflowContext,
        request: TargetedResearchRequest,
    ) -> TargetedResearchIterationResult:
        if self._on_run is not None:
            self._on_run(context, request)

        design = context.workflow_template.research_design_snapshot
        if design is None:
            raise ValueError("research_design_snapshot is required")

        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        source_id = (
            f"det-target-src-{request.information_need_id}-a{request.attempt}"
        )
        canonical_url = (
            f"https://deterministic.test/{request.information_need_id}/"
            f"a{request.attempt}"
        )

        existing = self._source_repository.get_by_canonical_url_for_project(
            project_id,
            canonical_url,
        )
        if existing is None:
            source = Source(
                id=source_id,
                project_id=project_id,
                url=canonical_url,
                canonical_url=canonical_url,
                title=f"Deterministic targeted source for {request.information_need_id}",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                content_text=(
                    f"Deterministic content for need {request.information_need_id} "
                    f"attempt {request.attempt}."
                ),
                content_checksum=f"checksum-{source_id}",
                research_question_refs=(request.research_question_id,),
                information_need_refs=(request.information_need_id,),
                workflow_run_refs=(workflow_run_id,),
                research_design_refs=(design.id,),
                retrieval_status=RetrievalStatus.ACQUIRED,
            )
            self._source_repository.create(source)
            source_ids = (source_id,)
            sources_acquired = 1
        else:
            source_ids = (existing.id,)
            sources_acquired = 0

        evidence_id = (
            f"det-target-ev-{request.information_need_id}-a{request.attempt}"
        )
        dedup_key = (
            f"{workflow_run_id}:{request.information_need_id}:"
            f"a{request.attempt}"
        )
        existing_evidence = self._evidence_repository.get_by_deduplication_key(
            workflow_run_id,
            dedup_key,
        )
        if existing_evidence is None:
            evidence = Evidence(
                id=evidence_id,
                project_id=project_id,
                source_id=source_ids[0],
                source_content_checksum=f"checksum-{source_ids[0]}",
                workflow_run_id=workflow_run_id,
                research_design_id=design.id,
                statement=(
                    f"Deterministic evidence for {request.information_need_id} "
                    f"attempt {request.attempt}."
                ),
                source_excerpt="Deterministic excerpt.",
                created_at=datetime.now(timezone.utc).isoformat(),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                research_question_refs=(request.research_question_id,),
                information_need_refs=(request.information_need_id,),
                deduplication_key=dedup_key,
                extraction_method="deterministic_targeted",
            )
            self._evidence_repository.create(evidence)
            evidence_ids = (evidence_id,)
            evidence_extracted = 1
        else:
            evidence_ids = (existing_evidence.id,)
            evidence_extracted = 0

        return TargetedResearchIterationResult(
            source_ids=source_ids,
            evidence_ids=evidence_ids,
            queries_executed=1,
            sources_acquired=sources_acquired,
            evidence_extracted=evidence_extracted,
        )
