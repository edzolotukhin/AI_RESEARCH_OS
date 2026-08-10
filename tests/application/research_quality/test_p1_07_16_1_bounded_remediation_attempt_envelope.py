"""P1-07.16.1 bounded remediations-attempt Evidence envelope."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.gap_type import GapType
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.config import ApplicationConfig
from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.execution.budget_utils import (
    EVIDENCE_PURPOSE_INITIAL,
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
)
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    _current_evidence_purpose,
    _current_stage,
    set_evidence_call_purpose,
    set_execution_stage,
)
from application.execution.remediation_attempt_envelope import (
    EXTRACTION_BOUNDED_PARTIAL,
    EXTRACTION_FULLY_PROCESSED,
    EXTRACTION_ORDERING_DOCUMENT_ORDER,
    SHARED_REMEDIATION_EXTRACTION_KEY,
    remediations_reserved_remaining,
)
from application.ports.evidence_ports import EvidenceCandidate
from application.research_quality.gap_scheduler import (
    COHORT_FIRST_OPPORTUNITY,
    decide_next_actionable_gap,
)
from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.targeted_research_runner import (
    TargetedResearchIterationResult,
)
from application.sources.source_need_exhaustion import (
    exhausted_canonical_urls_for_need,
    qualifying_zero_yield_source_need_pairs,
    work_item_is_valid_zero_yield,
)
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext

from tests.application.research_quality.test_p1_07_10_1_full_pipeline_acceptance_profile import (
    LOWCOST_PATH,
    OVERLAY_PATH,
    PROFILE_B_WORKER,
)
from tests.application.research_quality.test_targeted_research_loop import (
    SequentialSufficiencyEvaluator,
    _build_service,
    _context,
    _design_two_needs,
    _need_assessment,
    _result_for_needs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHUNK_CHARS = 40
CHUNK_OVERLAP = 5
LONG_SOURCE_CHARS = 220
SHORT_SOURCE_CHARS = 70
ATTEMPT_CAP = 3
PROFILE_B_RESERVED = 6


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What is the market outlook?",
                objective_refs=(),
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Market size data",
            ),
        ),
    )


def _template(design: ResearchDesign) -> WorkflowTemplate:
    return WorkflowTemplate(
        id="template-1",
        name="Desk",
        task_definitions=[
            TaskDefinition(
                id="task-extract-evidence",
                name="Extract",
                executor_id="evidence",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
    )


def _workflow_context(*, run_id: str = "run-16-1") -> WorkflowContext:
    design = _design()
    template = _template(design)
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = run_id
    context = WorkflowContext(
        project=Project(id="project-1", name="Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _source(*, run_id: str, content: str, source_id: str = "source-1") -> Source:
    return Source(
        id=source_id,
        project_id="project-1",
        url=f"https://example.com/{source_id}",
        canonical_url=f"https://example.com/{source_id}",
        title="Report",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=f"checksum-{source_id}",
        workflow_run_refs=(run_id,),
        research_design_refs=("design-1",),
        information_need_refs=("in-1",),
        research_question_refs=("rq-1",),
        metadata={
            "discovery_records": [
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-1",
                    "rank": 1,
                    "workflow_run_id": run_id,
                    "research_design_id": "design-1",
                },
            ],
        },
    )


def _profile_b_budget() -> ExecutionBudget:
    return ExecutionBudget(
        llm_max_calls_per_run=120,
        evidence_max_llm_calls=36,
        evidence_remediation_reserved_llm_calls=PROFILE_B_RESERVED,
        sufficiency_max_llm_calls=36,
        analysis_max_llm_calls=10,
        report_max_llm_calls=12,
        review_max_llm_calls=3,
    )


def _spend_initial(budget: ExecutionBudget) -> None:
    for _ in range(budget.evidence_initial_allowance):
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)


class _BillingEmptyExtractor:
    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, *, source, design, run_context):
        self.extract_calls += 1
        budget = _current_budget.get()
        if budget is not None:
            purpose = _current_evidence_purpose.get()
            budget.assert_can_call("evidence", purpose=purpose)
            budget.record_llm_call("evidence", purpose=purpose)
        return []


class _GroundingExtractor:
    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, *, source, design, run_context):
        self.extract_calls += 1
        budget = _current_budget.get()
        if budget is not None:
            purpose = _current_evidence_purpose.get()
            budget.assert_can_call("evidence", purpose=purpose)
            budget.record_llm_call("evidence", purpose=purpose)
        excerpt = "Exact excerpt in source."
        if excerpt not in (source.content_text or ""):
            return []
        return [
            EvidenceCandidate(
                statement="Market size is growing.",
                source_excerpt=excerpt,
                evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                research_question_refs=("rq-1",),
                information_need_refs=("in-1",),
                confidence=0.9,
            ),
        ]


class _DoubleGenerateExtractor:
    def __init__(self, client: BudgetEnforcingLLMClient) -> None:
        self.client = client
        self.generate_calls = 0

    def extract(self, *, source, design, run_context):
        for _ in range(2):
            self.client.generate(Prompt(system="s", user="u"))
            self.generate_calls += 1
        return []


class _BoundedPartialRunner:
    def __init__(
        self,
        *,
        bill_calls: int = ATTEMPT_CAP,
        evidence_extracted: int = 0,
        processing_state: str = EXTRACTION_BOUNDED_PARTIAL,
        persist_evidence: bool = False,
        evidence_repository: InMemoryEvidenceRepository | None = None,
    ) -> None:
        self.bill_calls = bill_calls
        self.evidence_extracted = evidence_extracted
        self.processing_state = processing_state
        self.persist_evidence = persist_evidence
        self.evidence_repository = evidence_repository
        self.targeted_need_ids: list[str] = []
        self.search_calls = 0
        self.planner_calls = 0

    def run(self, context: WorkflowContext, request) -> TargetedResearchIterationResult:
        self.targeted_need_ids.append(request.information_need_id)
        budget = _current_budget.get()
        remaining_before = (
            remediations_reserved_remaining(budget) if budget is not None else None
        )
        if budget is not None:
            for _ in range(self.bill_calls):
                budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
                budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        remaining_after = (
            remediations_reserved_remaining(budget) if budget is not None else None
        )
        evidence_ids: tuple[str, ...] = ()
        if self.persist_evidence and self.evidence_repository is not None:
            evidence_id = f"ev-{request.information_need_id}-{request.attempt}"
            self.evidence_repository.create(
                Evidence(
                    id=evidence_id,
                    project_id=context.project.id,
                    source_id="src-bounded",
                    source_content_checksum="checksum-src-bounded",
                    workflow_run_id=context.workflow_run.id,
                    research_design_id="design-1",
                    statement="Bounded remediations evidence.",
                    source_excerpt="excerpt",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    evidence_type=EvidenceType.DIRECT_EXCERPT,
                    research_question_refs=(request.research_question_id,),
                    information_need_refs=(request.information_need_id,),
                    deduplication_key=f"{context.workflow_run.id}:{evidence_id}",
                    extraction_method="test_bounded",
                ),
            )
            evidence_ids = (evidence_id,)
        planned = 6 if self.processing_state == EXTRACTION_BOUNDED_PARTIAL else self.bill_calls
        processed = self.bill_calls
        return TargetedResearchIterationResult(
            source_ids=("src-bounded",),
            evidence_ids=evidence_ids,
            queries_executed=1,
            sources_acquired=1,
            evidence_extracted=self.evidence_extracted,
            extraction_attempted=True,
            budget_stop_reason=None,
            extraction_processing_state=self.processing_state,
            remediation_attempt_diagnostics={
                "source_ids": ["src-bounded"],
                "extraction_ordering": EXTRACTION_ORDERING_DOCUMENT_ORDER,
                "planned_chunk_count": planned,
                "processed_chunk_count": processed,
                "skipped_chunk_count": max(0, planned - processed),
                "configured_attempt_call_cap": ATTEMPT_CAP,
                "effective_attempt_call_cap": self.bill_calls,
                "remediation_calls_remaining_before": remaining_before,
                "actual_evidence_calls_consumed": self.bill_calls,
                "remediation_calls_remaining_after": remaining_after,
                "capped": self.processing_state == EXTRACTION_BOUNDED_PARTIAL,
                "processing_state": self.processing_state,
                "attempt_completed": True,
            },
        )


def _bind_remediation(budget: ExecutionBudget):
    tokens = (
        _current_budget.set(budget),
        _current_stage.set("evidence"),
        _current_evidence_purpose.set(EVIDENCE_PURPOSE_REMEDIATION),
    )
    set_execution_stage("evidence")
    set_evidence_call_purpose(EVIDENCE_PURPOSE_REMEDIATION)
    return tokens


def _reset_bind(tokens) -> None:
    _current_budget.reset(tokens[0])
    _current_stage.reset(tokens[1])
    _current_evidence_purpose.reset(tokens[2])


def _extract_service(extractor) -> tuple[
    EvidenceExtractionService,
    InMemorySourceRepository,
    InMemoryEvidenceRepository,
]:
    sources = InMemorySourceRepository()
    evidence = InMemoryEvidenceRepository()
    chunked = ChunkedEvidenceExtractor(
        extractor,
        chunk_chars=CHUNK_CHARS,
        overlap_chars=CHUNK_OVERLAP,
    )
    service = EvidenceExtractionService(
        evidence_extractor=chunked,
        evidence_repository=evidence,
        source_repository=sources,
    )
    return service, sources, evidence


class ProfileBConfigTests(unittest.TestCase):
    def test_profile_b_attempt_envelope_is_three(self) -> None:
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_MAX_LLM_CALLS"], "36")
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS"], "6")
        self.assertEqual(
            PROFILE_B_WORKER["EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT"],
            "3",
        )
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        self.assertIn('EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT: "3"', overlay)
        self.assertIn('EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS: "6"', overlay)
        self.assertIn('EVIDENCE_MAX_LLM_CALLS: "36"', overlay)
        self.assertIn('TARGETED_MAX_ATTEMPTS_PER_GAP: "2"', overlay)
        self.assertIn('RESEARCH_MAX_GAP_ROUNDS_PER_RUN: "2"', overlay)
        self.assertIn('TARGETED_MAX_QUERIES_PER_GAP: "1"', overlay)
        self.assertIn('TARGETED_MAX_SOURCES_PER_GAP: "1"', overlay)
        self.assertIn('LLM_MAX_CALLS_PER_RUN: "120"', overlay)

    def test_lowcost_and_default_remain_disabled(self) -> None:
        lowcost = LOWCOST_PATH.read_text(encoding="utf-8")
        self.assertNotIn("EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT", lowcost)
        self.assertEqual(
            ApplicationConfig().evidence_remediation_max_llm_calls_per_attempt,
            0,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT", None)
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_remediation_max_llm_calls_per_attempt, 0)

    def test_from_env_maps_profile_b_attempt_cap(self) -> None:
        env = {
            "EVIDENCE_MAX_LLM_CALLS": "36",
            "EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS": "6",
            "EVIDENCE_REMEDIATION_MAX_LLM_CALLS_PER_ATTEMPT": "3",
        }
        with patch.dict(os.environ, env, clear=False):
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_max_llm_calls, 36)
        self.assertEqual(config.evidence_remediation_reserved_llm_calls, 6)
        self.assertEqual(config.evidence_remediation_max_llm_calls_per_attempt, 3)


class BoundedRemediationExtractTests(unittest.TestCase):
    def test_case_1_profile_b_attempt_envelope(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="A" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertEqual(extractor.extract_calls, ATTEMPT_CAP)
        self.assertEqual(budget.evidence_remediation_calls, ATTEMPT_CAP)
        self.assertEqual(remediations_reserved_remaining(budget), 3)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_BOUNDED_PARTIAL)
        self.assertIsNone(summary.budget_stop_reason)
        self.assertFalse(summary.evidence_stage_budget_exhausted)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertGreater(diagnostics.planned_work_items, ATTEMPT_CAP)
        self.assertEqual(diagnostics.processed_work_items, ATTEMPT_CAP)
        self.assertEqual(diagnostics.skipped_work_items, diagnostics.planned_work_items - 3)
        self.assertTrue(diagnostics.remediation_attempt_capped)
        self.assertEqual(diagnostics.remediation_attempt_configured_limit, 3)
        self.assertEqual(diagnostics.remediation_attempt_effective_limit, 3)

    def test_case_5_fully_processed_short_source(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="B" * SHORT_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertLess(extractor.extract_calls, ATTEMPT_CAP)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_FULLY_PROCESSED)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        self.assertEqual(diagnostics.skipped_work_items, 0)
        self.assertFalse(diagnostics.remediation_attempt_capped)

    def test_case_6_two_attempts_cannot_expand_reserve(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="C" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            first = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
            second = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertEqual(budget.evidence_remediation_calls, PROFILE_B_RESERVED)
        self.assertEqual(first.diagnostics.remediation_attempt_calls_consumed, 3)
        self.assertEqual(second.diagnostics.remediation_attempt_calls_consumed, 3)
        self.assertEqual(remediations_reserved_remaining(budget), 0)

    def test_case_7_remaining_smaller_than_cap(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        for _ in range(4):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="D" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertEqual(extractor.extract_calls, 2)
        self.assertEqual(budget.evidence_remediation_calls, PROFILE_B_RESERVED)
        self.assertEqual(remediations_reserved_remaining(budget), 0)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_BOUNDED_PARTIAL)
        self.assertEqual(summary.diagnostics.remediation_attempt_effective_limit, 2)

    def test_case_8_local_cap_is_not_global_exhaustion(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="E" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertNotEqual(summary.budget_stop_reason, EVIDENCE_REMEDIATION_BUDGET_REASON)
        self.assertIsNone(summary.budget_stop_reason)
        self.assertEqual(remediations_reserved_remaining(budget), 3)

    def test_case_15_legacy_unlimited_per_attempt(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="F" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=0,
            )
        finally:
            _reset_bind(tokens)
        self.assertEqual(budget.evidence_remediation_calls, PROFILE_B_RESERVED)
        self.assertGreater(extractor.extract_calls, ATTEMPT_CAP)
        self.assertEqual(summary.budget_stop_reason, EVIDENCE_REMEDIATION_BUDGET_REASON)
        self.assertNotEqual(summary.extraction_processing_state, EXTRACTION_BOUNDED_PARTIAL)

    def test_case_16_initial_extraction_uncapped(self) -> None:
        budget = _profile_b_budget()
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="G" * LONG_SOURCE_CHARS))
        token_b = _current_budget.set(budget)
        token_s = _current_stage.set("evidence")
        token_p = _current_evidence_purpose.set(EVIDENCE_PURPOSE_INITIAL)
        set_execution_stage("evidence")
        set_evidence_call_purpose(EVIDENCE_PURPOSE_INITIAL)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _current_budget.reset(token_b)
            _current_stage.reset(token_s)
            _current_evidence_purpose.reset(token_p)
        self.assertGreater(extractor.extract_calls, ATTEMPT_CAP)
        self.assertEqual(budget.evidence_remediation_calls, 0)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_FULLY_PROCESSED)

    def test_case_17_actual_calls_authoritative_with_retries(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        delegate = Mock()
        delegate.generate.return_value = LLMResponse(content="{}", output_tokens=1)
        client = BudgetEnforcingLLMClient(delegate)
        extractor = _DoubleGenerateExtractor(client)
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="H" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertEqual(budget.evidence_remediation_calls, ATTEMPT_CAP)
        self.assertEqual(delegate.generate.call_count, ATTEMPT_CAP)
        self.assertLessEqual(extractor.generate_calls, ATTEMPT_CAP)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_BOUNDED_PARTIAL)

    def test_case_4_some_evidence_under_local_cap(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _GroundingExtractor()
        service, sources, evidence_repo = _extract_service(extractor)
        context = _workflow_context()
        content = "Exact excerpt in source. " + ("Z" * LONG_SOURCE_CHARS)
        sources.create(_source(run_id=context.workflow_run.id, content=content))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        self.assertGreater(summary.evidence_extracted, 0)
        self.assertEqual(extractor.extract_calls, ATTEMPT_CAP)
        stored = evidence_repo.list_for_project(
            "project-1",
            workflow_run_id=context.workflow_run.id,
        )
        self.assertGreater(len(stored), 0)
        self.assertEqual(summary.extraction_processing_state, EXTRACTION_BOUNDED_PARTIAL)


class BoundedRemediationLoopTests(unittest.TestCase):
    def tearDown(self) -> None:
        _current_budget.set(None)

    def test_case_2_and_20_history_and_decision_two(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        token = _current_budget.set(budget)
        runner = _BoundedPartialRunner()
        missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([missing]),
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=_design_two_needs())
        try:
            result = service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        decisions = loop["scheduler_decisions"]
        self.assertGreaterEqual(len(decisions), 2)
        self.assertEqual(decisions[0]["selected_need_id"], "in-1")
        self.assertEqual(decisions[0]["selection_reason"], COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(decisions[1]["selected_need_id"], "in-2")
        self.assertEqual(decisions[1]["selection_reason"], COHORT_FIRST_OPPORTUNITY)
        self.assertEqual(runner.targeted_need_ids[0], "in-1")
        self.assertEqual(runner.targeted_need_ids[1], "in-2")
        self.assertEqual(runner.search_calls, 0)
        self.assertEqual(runner.planner_calls, 0)
        self.assertEqual(loop["pending_targeted_need_id"], "")
        self.assertEqual(loop["pending_attempt"], 0)
        self.assertGreaterEqual(len(loop["history"]), 1)
        first_history = loop["history"][0]
        self.assertIn("in-1", first_history["targeted_need_ids"])
        self.assertTrue(first_history["remediation_attempt_diagnostics"]["attempt_completed"])
        self.assertEqual(
            first_history["remediation_attempt_diagnostics"]["processing_state"],
            EXTRACTION_BOUNDED_PARTIAL,
        )
        self.assertNotEqual(result.termination_reason, EVIDENCE_REMEDIATION_BUDGET_REASON)
        self.assertEqual(budget.evidence_remediation_calls, 6)
        self.assertEqual(loop["gap_attempt_counts"].get("in-1"), 1)

    def test_case_3_zero_evidence_still_completes(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        token = _current_budget.set(budget)
        runner = _BoundedPartialRunner(evidence_extracted=0)
        missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([missing]),
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=_design_two_needs())
        try:
            service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        first = loop["history"][0]
        self.assertFalse(first["improved"])
        self.assertEqual(first["new_evidence_count"], 0)
        self.assertEqual(loop["pending_targeted_need_id"], "")
        self.assertIn("in-2", [item["selected_need_id"] for item in loop["scheduler_decisions"]])

    def test_case_4_loop_evidence_and_reassessment(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        token = _current_budget.set(budget)
        evidence_repo = InMemoryEvidenceRepository()
        runner = _BoundedPartialRunner(
            evidence_extracted=1,
            persist_evidence=True,
            evidence_repository=evidence_repo,
        )
        initial = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        after = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.PARTIAL),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([initial, after]),
            evidence_repository=evidence_repo,
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=_design_two_needs())
        try:
            service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        first = loop["history"][0]
        self.assertTrue(first["improved"])
        self.assertEqual(first["new_evidence_count"], 1)
        stored = evidence_repo.list_for_project("project-1", workflow_run_id=context.workflow_run.id)
        self.assertGreaterEqual(len(stored), 1)
        self.assertTrue(any("in-1" in row.information_need_refs for row in stored))

    def test_case_9_and_10_global_zero_after_bounded_attempt(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        for _ in range(4):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        token = _current_budget.set(budget)
        runner = _BoundedPartialRunner(bill_calls=2)
        missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([missing]),
            runner=runner,
            max_rounds=1,
        )
        context = _context(design=_design_two_needs())
        try:
            result = service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        self.assertEqual(len(runner.targeted_need_ids), 1)
        self.assertEqual(loop["pending_targeted_need_id"], "")
        self.assertEqual(loop["pending_attempt"], 0)
        self.assertEqual(len(loop["history"]), 1)
        self.assertEqual(loop["gap_attempt_counts"]["in-1"], 1)
        self.assertEqual(result.termination_reason, EVIDENCE_REMEDIATION_BUDGET_REASON)
        self.assertEqual(budget.evidence_remediation_calls, PROFILE_B_RESERVED)
        selected = [item["selected_need_id"] for item in loop["scheduler_decisions"]]
        self.assertEqual(selected, ["in-1"])

    def test_case_11_bounded_partial_counts_toward_attempts(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        token = _current_budget.set(budget)
        runner = _BoundedPartialRunner()
        missing = _result_for_needs(
            _need_assessment(need_id="in-1", rq_id="rq-1", status=SufficiencyStatus.MISSING),
            _need_assessment(need_id="in-2", rq_id="rq-2", status=SufficiencyStatus.MISSING),
        )
        service = _build_service(
            SequentialSufficiencyEvaluator([missing]),
            runner=runner,
            max_rounds=1,
            max_attempts_per_gap=2,
        )
        context = _context(design=_design_two_needs())
        try:
            service.assess_and_apply(context)
        finally:
            _current_budget.reset(token)
        loop = context.read_shared(SHARED_LOOP_STATE_KEY)
        self.assertEqual(loop["gap_attempt_counts"]["in-1"], 1)
        self.assertEqual(loop["gap_attempt_counts"].get("in-2"), 1)

    def test_case_18_no_new_llm_stages(self) -> None:
        runner_source = (
            REPO_ROOT
            / "application"
            / "research_quality"
            / "production_targeted_research_runner.py"
        ).read_text(encoding="utf-8")
        extract_source = (
            REPO_ROOT / "application" / "evidence" / "evidence_extraction_service.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("rank_chunks", runner_source)
        self.assertNotIn("missing_aspects_only", extract_source)
        scheduler_source = (
            REPO_ROOT / "application" / "research_quality" / "gap_scheduler.py"
        ).read_text(encoding="utf-8")
        self.assertIn("COHORT_FIRST_OPPORTUNITY", scheduler_source)
        self.assertIn("gap_attempt_counts.get(request.information_need_id, 0) == 0", scheduler_source)


class SourceExhaustionSafetyTests(unittest.TestCase):
    def test_case_12_bounded_partial_zero_yield_not_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_items = (
            {
                "source_id": "source-s",
                "information_need_ids": ["IN1"],
                "extractor_status": "no_candidates",
                "source_processing_state": EXTRACTION_BOUNDED_PARTIAL,
                "inner_chunks": [
                    {
                        "extractor_status": "success",
                        "raw_candidate_count": 0,
                        "response_shape": {"response_classification": "valid_empty_result"},
                    }
                ],
            },
        )
        self.assertTrue(work_item_is_valid_zero_yield(work_items[0]))
        self.assertEqual(qualifying_zero_yield_source_need_pairs(work_items), frozenset())
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=work_items,
        )
        self.assertEqual(exhausted, frozenset())

    def test_case_13_fully_processed_valid_empty_may_exhaust(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_items = (
            {
                "source_id": "source-s",
                "information_need_ids": ["IN1"],
                "extractor_status": "no_candidates",
                "source_processing_state": EXTRACTION_FULLY_PROCESSED,
                "inner_chunks": [
                    {
                        "extractor_status": "success",
                        "raw_candidate_count": 0,
                        "response_shape": {"response_classification": "valid_empty_result"},
                    }
                ],
            },
        )
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=work_items,
        )
        self.assertEqual(exhausted, frozenset({source.canonical_url}))

    def test_case_14_invalid_json_still_not_exhausted(self) -> None:
        source = Source(
            id="source-s",
            project_id="p",
            url="https://shared.example/page",
            canonical_url="https://shared.example/page",
            title="Shared",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
        )
        work_item = {
            "source_id": "source-s",
            "information_need_ids": ["IN1"],
            "extractor_status": "no_candidates",
            "source_processing_state": EXTRACTION_FULLY_PROCESSED,
            "inner_chunks": [
                {
                    "extractor_status": "exception",
                    "exception_class": "EvidenceResponseOutcomeError",
                    "response_shape": {"response_classification": "invalid_json"},
                }
            ],
        }
        self.assertFalse(work_item_is_valid_zero_yield(work_item))
        exhausted = exhausted_canonical_urls_for_need(
            information_need_id="IN1",
            sources=[source],
            evidence_rows=(),
            work_items=(work_item,),
        )
        self.assertEqual(exhausted, frozenset())

    def test_remediation_extraction_shared_state_is_consulted(self) -> None:
        shared = {
            SHARED_REMEDIATION_EXTRACTION_KEY: {
                "diagnostics": {
                    "extraction_processing_state": EXTRACTION_BOUNDED_PARTIAL,
                    "work_items": [
                        {
                            "source_id": "source-s",
                            "information_need_ids": ["IN1"],
                            "extractor_status": "no_candidates",
                        }
                    ],
                }
            }
        }
        from application.sources.source_need_exhaustion import extraction_work_items

        items = extraction_work_items(shared)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_processing_state"], EXTRACTION_BOUNDED_PARTIAL)
        self.assertEqual(qualifying_zero_yield_source_need_pairs(items), frozenset())


class ObservabilityAndInvariantTests(unittest.TestCase):
    def test_case_19_diagnostics_report_cap(self) -> None:
        budget = _profile_b_budget()
        _spend_initial(budget)
        extractor = _BillingEmptyExtractor()
        service, sources, _evidence = _extract_service(extractor)
        context = _workflow_context()
        sources.create(_source(run_id=context.workflow_run.id, content="I" * LONG_SOURCE_CHARS))
        tokens = _bind_remediation(budget)
        try:
            summary = service.extract_for_source_ids(
                context,
                ("source-1",),
                allow_empty=True,
                attempt_max_llm_calls=ATTEMPT_CAP,
            )
        finally:
            _reset_bind(tokens)
        diagnostics = summary.diagnostics
        assert diagnostics is not None
        payload = diagnostics.to_dict()
        self.assertGreater(payload["planned_work_items"], payload["processed_work_items"])
        self.assertEqual(payload["remediation_attempt_configured_limit"], 3)
        self.assertEqual(payload["remediation_attempt_calls_consumed"], 3)
        self.assertEqual(payload["extraction_processing_state"], EXTRACTION_BOUNDED_PARTIAL)
        self.assertEqual(payload["remediation_calls_remaining_after"], 3)
        self.assertEqual(payload["extraction_ordering"], EXTRACTION_ORDERING_DOCUMENT_ORDER)

    def test_scheduler_source_unchanged_first_opportunity(self) -> None:
        gaps = (
            TargetedResearchRequest(
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_id="rq-1",
                information_need_id="in-1",
                gap_types=(GapType.NO_EVIDENCE,),
                attempt=2,
            ),
            TargetedResearchRequest(
                workflow_run_id="run-1",
                research_design_id="design-1",
                research_question_id="rq-2",
                information_need_id="in-2",
                gap_types=(GapType.NO_EVIDENCE,),
                attempt=1,
            ),
        )
        decision = decide_next_actionable_gap(
            gaps,
            gap_attempt_counts={"in-1": 1},
            stalled_need_ids=set(),
            max_attempts_per_gap=2,
            remaining_remediation_evidence_calls=3,
            prior_improved_need_ids={"in-1"},
        )
        self.assertEqual(decision.selected.information_need_id, "in-2")
        self.assertEqual(decision.selection_reason, COHORT_FIRST_OPPORTUNITY)


if __name__ == "__main__":
    unittest.main()
