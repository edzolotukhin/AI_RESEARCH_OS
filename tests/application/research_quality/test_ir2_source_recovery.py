from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from application.evidence.content_chunking import SourceContentChunk
from application.evidence.evidence_extraction_diagnostics import (
    EvidenceExtractionDiagnostics,
    EvidenceStageFailureClassification,
)
from application.evidence.evidence_extraction_scheduler import (
    EvidenceExtractionWorkItem,
    PHASE_FIRST_OPPORTUNITY,
    build_need_fair_extraction_queue,
    extraction_retry_identity,
)
from application.evidence.evidence_extraction_service import (
    EvidenceExtractionService,
    EvidenceExtractionSummary,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.research_quality.evidence_gap_priority import design_priority_by_need
from application.research_quality.gap_scheduler import decide_next_actionable_gap
from application.research_quality.production_targeted_research_runner import (
    ProductionTargetedResearchRunner,
)
from application.research_quality.research_loop_state import (
    ResearchLoopIterationRecord,
    ResearchLoopState,
)
from application.sources.source_acquisition_service import (
    SourceAcquisitionService,
    SourceAcquisitionSummary,
    _safe_attempt_diagnostics,
)
from application.sources.source_need_exhaustion import (
    completed_low_value_operation_ids,
    completed_low_value_source_need_identities,
    work_item_is_completed_low_value,
)
from domain.planning.derivation import (
    DerivationContract,
    DerivationOperation,
    InformationNeedKind,
)
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.gap_type import GapType
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design",
        research_questions=(ResearchQuestion(id="rq", question="Q"),),
        information_needs=(
            InformationNeed(id="in-low", research_question_id="rq", description="low", priority=1),
            InformationNeed(id="in-prerequisite", research_question_id="rq", description="required", priority=5),
            InformationNeed(
                id="in-derived", research_question_id="rq", description="change",
                priority=1, kind=InformationNeedKind.DERIVED,
                depends_on_information_need_ids=("in-prerequisite",),
                derivation=DerivationContract(
                    operation_type=DerivationOperation.CUMULATIVE_ABSOLUTE_CHANGE,
                    metric="population", input_unit="persons", geography="Ukraine",
                    required_periods=("2020", "2021"),
                ),
            ),
        ),
    )


def _source(*, revision: int = 1, checksum: str = "checksum") -> Source:
    return Source(
        id="source",
        project_id="project",
        url="https://example.test/source",
        canonical_url="https://example.test/source",
        title="source",
        retrieval_status=RetrievalStatus.TRUNCATED,
        content_text="bounded source content",
        content_checksum=checksum,
        content_revision=revision,
        extraction_revision="extract-v1",
        workflow_run_refs=("run",),
        research_design_refs=("design",),
        information_need_refs=("in-low", "in-prerequisite"),
        research_question_refs=("rq",),
        query_refs=("query",),
        metadata={"truncated": True, "discovery_records": [{
            "workflow_run_id": "run", "research_design_id": "design",
            "information_need_id": "in-prerequisite", "research_question_id": "rq",
            "query_id": "query",
        }]},
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def _request(need_id: str) -> TargetedResearchRequest:
    return TargetedResearchRequest(
        workflow_run_id="run", research_design_id="design",
        research_question_id="rq", information_need_id=need_id,
        gap_types=(GapType.NO_EVIDENCE,),
    )


def _low_value_item(operation_id: str, retry_identity: str) -> dict:
    return {
        "source_id": "source",
        "information_need_ids": ["in-prerequisite"],
        "primary_need_id": "in-prerequisite",
        "extractor_status": "success",
        "failure_categories": ["provenance_rejection"],
        "candidate_outcomes": [{"outcome": "rejected"}],
        "operation_id": operation_id,
        "source_retry_identity": retry_identity,
    }


class IR2SourceRecoveryTests(unittest.TestCase):
    def test_design_priority_survives_gap_and_extraction_scheduling(self) -> None:
        design = _design()
        priorities = design_priority_by_need(design)
        self.assertLess(priorities["in-prerequisite"], priorities["in-low"])
        self.assertLess(priorities["in-low"], priorities["in-derived"])
        decision = decide_next_actionable_gap(
            (_request("in-low"), _request("in-prerequisite")),
            gap_attempt_counts={}, stalled_need_ids=set(), max_attempts_per_gap=2,
            evidence_priority_by_need={"in-low": 0, "in-prerequisite": 0},
            design_priority_by_need=design_priority_by_need(design),
        )
        self.assertEqual(decision.selected.information_need_id, "in-prerequisite")
        queue = build_need_fair_extraction_queue(
            [_source()], design=design, workflow_run_id="run",
            research_design_id="design", chunk_chars=100, overlap_chars=0,
        )
        self.assertEqual(queue[0].primary_need_id, "in-prerequisite")

        acquisition = object.__new__(SourceAcquisitionService)
        acquisition._budget = SimpleNamespace(min_information_need_coverage_ratio=1.0)
        self.assertTrue(acquisition._coverage_target_satisfied(
            design,
            {"in-low", "in-prerequisite"},
            {"rq"},
        ))

    def test_completed_rejection_is_durable_and_changed_revision_is_retryable(self) -> None:
        source = _source()
        context = RunScopedSourceContext(
            workflow_run_id="run", research_design_id="design",
            information_need_ids=("in-prerequisite",), research_question_ids=("rq",),
            query_ids=("query",),
        )
        item = EvidenceExtractionWorkItem(
            source=source, chunk=SourceContentChunk("bounded source content", 0, 22),
            run_context=context, phase=PHASE_FIRST_OPPORTUNITY,
            source_first_attempt=True, primary_need_id="in-prerequisite",
        )
        operation_id = EvidenceExtractionService._work_item_operation_id(
            item, workflow_run_id="run",
        )
        retry_identity = extraction_retry_identity(source)
        shared = {"evidence_extraction": {"diagnostics": {"work_items": [
            _low_value_item(operation_id, retry_identity),
            _low_value_item(operation_id, retry_identity),
        ]}}}
        self.assertEqual(completed_low_value_operation_ids(shared), {operation_id})
        self.assertEqual(
            completed_low_value_source_need_identities(shared),
            {("source", "in-prerequisite", retry_identity)},
        )
        changed = _source(revision=2)
        changed_item = EvidenceExtractionWorkItem(
            source=changed, chunk=item.chunk, run_context=context,
            phase=item.phase, source_first_attempt=True,
            primary_need_id=item.primary_need_id,
        )
        self.assertNotEqual(
            operation_id,
            EvidenceExtractionService._work_item_operation_id(
                changed_item, workflow_run_id="run",
            ),
        )

    def test_technical_and_budget_failures_are_not_semantic_exhaustion(self) -> None:
        for category, status in (
            ("provider_exception", "exception"),
            ("budget_stop", "budget_stop"),
        ):
            item = _low_value_item("operation", "identity")
            item["extractor_status"] = status
            item["failure_categories"] = [category]
            self.assertFalse(work_item_is_completed_low_value(item))

    def test_recovery_decisions_distinguish_transport_unsupported_empty_and_rejection(self) -> None:
        def evidence(classification: str) -> EvidenceExtractionSummary:
            diagnostics = EvidenceExtractionDiagnostics(workflow_run_id="run")
            diagnostics.failure_classification = classification
            return EvidenceExtractionSummary((), 1, 0, 0, 1, diagnostics=diagnostics)

        unsupported = SourceAcquisitionSummary(
            (), 1, 1, 0, 1,
            failure_category_counts={"unsupported_content_type": 1},
        )
        self.assertEqual(
            ProductionTargetedResearchRunner._bounded_recovery_decision(
                evidence=evidence(EvidenceStageFailureClassification.NO_ELIGIBLE_SOURCES.value),
                acquisition=unsupported,
            ),
            ("unsupported_source_format", "alternate_supported_source"),
        )
        transport = SimpleNamespace(
            retrieval_failures=1, sources_acquired=0, source_ids=(), budget_exhausted=False,
            failure_category_counts={"http_error": 1}, truncated_count=0,
        )
        self.assertEqual(
            ProductionTargetedResearchRunner._bounded_recovery_decision(
                evidence=evidence(EvidenceStageFailureClassification.NO_ELIGIBLE_SOURCES.value),
                acquisition=transport,
            )[0],
            "retrieval_transport_failure",
        )
        acquired = SimpleNamespace(
            retrieval_failures=0, sources_acquired=1, source_ids=("source",), budget_exhausted=False,
            failure_category_counts={}, truncated_count=0,
        )
        self.assertEqual(
            ProductionTargetedResearchRunner._bounded_recovery_decision(
                evidence=evidence(EvidenceStageFailureClassification.NO_CANDIDATES.value),
                acquisition=acquired,
            )[0],
            "valid_source_zero_candidates",
        )
        self.assertEqual(
            ProductionTargetedResearchRunner._bounded_recovery_decision(
                evidence=evidence(EvidenceStageFailureClassification.PROVENANCE_REJECTED_ALL.value),
                acquisition=acquired,
            )[0],
            "provenance_rejection",
        )

    def test_source_eligibility_projection_is_sanitized_and_typed(self) -> None:
        decisions = [
            {"action": "fetch_failed", "information_need_id": "in-prerequisite",
             "retrieval_status": "unsupported", "failure_category": "unsupported_content_type"},
            {"action": "fetch_failed", "information_need_id": "in-prerequisite",
             "retrieval_status": "failed", "failure_category": "http_error"},
            {"action": "selected", "information_need_id": "in-prerequisite",
             "retrieval_status": "truncated"},
        ]
        records, truncated = _safe_attempt_diagnostics(decisions, _design())
        self.assertFalse(truncated)
        self.assertEqual(
            [item["source_eligibility"] for item in records],
            ["unsupported", "retrieval_failed", "acquired_truncated"],
        )

    def test_restart_round_trip_preserves_bounded_recovery_trace(self) -> None:
        state = ResearchLoopState(history=[ResearchLoopIterationRecord(
            attempt=1, round_number=1, blocking_need_ids_before=("in-prerequisite",),
            targeted_need_ids=("in-prerequisite",), queries_generated=1,
            new_sources_count=0, new_evidence_count=0, readiness_after={}, improved=False,
            remediation_attempt_diagnostics={
                "recovery_outcome": "provenance_rejection",
                "recovery_action": "alternate_source_or_explicit_correction",
                "candidate_rejection_codes": ["source_checksum_mismatch"],
                "completed_low_value_attempts": [
                    _low_value_item("persisted-operation", "persisted-identity"),
                ],
            },
        )])
        restored = ResearchLoopState.from_dict(state.to_dict())
        self.assertEqual(restored.to_dict(), state.to_dict())
        shared = {"research_loop_state": restored.to_dict()}
        self.assertEqual(
            completed_low_value_operation_ids(shared),
            {"persisted-operation"},
        )


if __name__ == "__main__":
    unittest.main()
