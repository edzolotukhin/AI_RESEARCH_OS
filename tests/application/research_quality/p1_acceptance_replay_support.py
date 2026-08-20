"""Shared fixtures and helpers for P1 RQCL acceptance replay tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence
from unittest.mock import Mock

from application.contracts.base_executor import BaseExecutor
from application.executors.analysis_executor import AnalysisExecutor
from application.executors.research_readiness_executor import ResearchReadinessExecutor
from application.execution.execution_budget_context import (
    ensure_run_budget,
    finalize_run_budget,
    get_execution_budget,
    set_execution_stage,
    stage_for_executor,
)
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.deterministic_targeted_research_runner import (
    DeterministicTargetedResearchRunner,
)
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.readiness_result_codec import extract_research_readiness
from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.research_readiness_service import (
    ResearchReadinessService,
    SHARED_STATE_KEY,
)
from application.research_quality.targeted_research_bounds import TargetedResearchBounds
from application.research_quality.research_loop_service import ResearchLoopService
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_outcome import ResearchOutcome
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus

from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)

from runtime.workflow_context import WorkflowContext

from tests.helpers.workflow_run_builder import make_task, make_workflow_run
from tests.application.research_quality.test_targeted_research_loop import (
    _store_completed_assessments,
)


# ---------------------------------------------------------------------------
# Information need identifiers (full acceptance design)
# ---------------------------------------------------------------------------

IN_RQ1_SUFFICIENT = "in-rq1-covered"
IN_RQ1_MISSING = "in-rq1-missing"
IN_RQ1_PARTIAL = "in-rq1-partial"
IN_RQ2_INSUFFICIENT = "in-rq2-insufficient"
IN_RQ2_BLOCKED = "in-rq2-blocked"
IN_RQ2_SUFFICIENT = "in-rq2-covered"
IN_RQ1_STUCK = "in-rq1-stuck"

RQ1 = "rq-market"
RQ2 = "rq-competition"


def need_assessment(
    *,
    need_id: str,
    rq_id: str,
    status: SufficiencyStatus,
    search_directives: tuple[str, ...] = ("targeted query",),
) -> InformationNeedAssessment:
    gap_types: tuple[GapType, ...] = ()
    evidence_count = 1
    if status == SufficiencyStatus.MISSING:
        gap_types = (GapType.NO_EVIDENCE,)
        evidence_count = 0
    elif status == SufficiencyStatus.BLOCKED:
        gap_types = (GapType.UNRESOLVABLE,)
    elif status in {SufficiencyStatus.PARTIAL, SufficiencyStatus.INSUFFICIENT}:
        gap_types = (GapType.INSUFFICIENT_DEPTH,)
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=status,
        evidence_count=evidence_count,
        gap_types=gap_types,
        search_directives=search_directives,
        reason=f"Acceptance fixture status={status.value}.",
    )


def result_for_needs(
    *assessments: InformationNeedAssessment,
    ready: bool | None = None,
) -> ResearchReadinessResult:
    by_rq: dict[str, list[InformationNeedAssessment]] = {}
    for assessment in assessments:
        by_rq.setdefault(assessment.research_question_id, []).append(assessment)

    rq_assessments = tuple(
        ResearchReadinessAssessment(
            research_question_id=rq_id,
            information_need_assessments=tuple(items),
            ready_for_analysis=all(
                item.status == SufficiencyStatus.SUFFICIENT for item in items
            ),
            blocking_information_need_ids=tuple(
                item.information_need_id
                for item in items
                if item.status
                in {
                    SufficiencyStatus.MISSING,
                    SufficiencyStatus.PARTIAL,
                    SufficiencyStatus.INSUFFICIENT,
                    SufficiencyStatus.BLOCKED,
                }
            ),
        )
        for rq_id, items in sorted(by_rq.items())
    )
    all_ready = ready
    if all_ready is None:
        all_ready = all(item.ready_for_analysis for item in rq_assessments)
    blocking_rq = tuple(
        item.research_question_id for item in rq_assessments if not item.ready_for_analysis
    )
    blocking_needs = tuple(
        need.information_need_id
        for item in rq_assessments
        for need in item.information_need_assessments
        if need.status
        in {
            SufficiencyStatus.MISSING,
            SufficiencyStatus.PARTIAL,
            SufficiencyStatus.INSUFFICIENT,
            SufficiencyStatus.BLOCKED,
        }
    )
    has_actionable = any(
        need.status
        in {
            SufficiencyStatus.MISSING,
            SufficiencyStatus.PARTIAL,
            SufficiencyStatus.INSUFFICIENT,
        }
        for item in rq_assessments
        for need in item.information_need_assessments
    )
    return ResearchReadinessResult(
        research_question_assessments=rq_assessments,
        ready_for_analysis=all_ready,
        blocking_research_question_ids=blocking_rq if not all_ready else (),
        blocking_information_need_ids=blocking_needs if not all_ready else (),
        targeted_research_required=has_actionable if not all_ready else False,
    )


def full_acceptance_design() -> ResearchDesign:
    """Multi-RQ design covering every sufficiency status class."""
    return ResearchDesign(
        id="p1-acceptance-design",
        research_questions=(
            ResearchQuestion(
                id=RQ1,
                question="What is the market outlook?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id=RQ2,
                question="Who are the competitors and channels?",
                objective_refs=(),
            ),
        ),
        information_needs=(
            InformationNeed(
                id=IN_RQ1_SUFFICIENT,
                research_question_id=RQ1,
                description="Already covered market context",
            ),
            InformationNeed(
                id=IN_RQ1_MISSING,
                research_question_id=RQ1,
                description="Missing quantitative market data",
            ),
            InformationNeed(
                id=IN_RQ1_PARTIAL,
                research_question_id=RQ1,
                description="Partial market trend coverage",
            ),
            InformationNeed(
                id=IN_RQ2_INSUFFICIENT,
                research_question_id=RQ2,
                description="Insufficient competitor depth",
            ),
            InformationNeed(
                id=IN_RQ2_BLOCKED,
                research_question_id=RQ2,
                description="Blocked proprietary channel data",
            ),
            InformationNeed(
                id=IN_RQ2_SUFFICIENT,
                research_question_id=RQ2,
                description="Competitor list already covered",
            ),
        ),
    )


def ready_scenario_design() -> ResearchDesign:
    """Actionable gaps only; no BLOCKED blockers in final state."""
    full = full_acceptance_design()
    return ResearchDesign(
        id="p1-ready-design",
        research_questions=full.research_questions,
        information_needs=tuple(
            need for need in full.information_needs if need.id != IN_RQ2_BLOCKED
        ),
    )


def gap_starvation_design() -> ResearchDesign:
    return ResearchDesign(
        id="p1-gap-starvation-design",
        research_questions=(
            ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ResearchQuestion(id="rq-3", question="Q3", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(id="in-1", research_question_id="rq-1", description="Gap 1"),
            InformationNeed(id="in-2", research_question_id="rq-2", description="Gap 2"),
            InformationNeed(id="in-3", research_question_id="rq-3", description="Gap 3"),
        ),
    )


def serbia_microgreens_design() -> ResearchDesign:
    """Live-shaped offline fixture inspired by Serbia microgreens acceptance."""
    return ResearchDesign(
        id="serbia-microgreens-design",
        research_questions=(
            ResearchQuestion(
                id="rq-market",
                question="What is the Serbia microgreens market size and maturity?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-horeca",
                question="What is HoReCa demand for microgreens?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-competitors",
                question="Who are competitors and channels?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-pricing",
                question="What are pricing and assortment norms?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-geography",
                question="What geography and distribution constraints apply?",
                objective_refs=(),
            ),
            ResearchQuestion(
                id="rq-regulatory",
                question="What buyer and regulatory requirements apply?",
                objective_refs=(),
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-market-size",
                research_question_id="rq-market",
                description="Quantitative market sizing",
            ),
            InformationNeed(
                id="in-market-maturity",
                research_question_id="rq-market",
                description="Market maturity signals",
            ),
            InformationNeed(
                id="in-horeca-demand",
                research_question_id="rq-horeca",
                description="HoReCa demand evidence",
            ),
            InformationNeed(
                id="in-competitors",
                research_question_id="rq-competitors",
                description="Competitor landscape",
            ),
            InformationNeed(
                id="in-channels",
                research_question_id="rq-competitors",
                description="Distribution channels",
            ),
            InformationNeed(
                id="in-pricing",
                research_question_id="rq-pricing",
                description="Pricing benchmarks",
            ),
            InformationNeed(
                id="in-geography",
                research_question_id="rq-geography",
                description="Geographic coverage",
            ),
            InformationNeed(
                id="in-regulatory-coverage",
                research_question_id="rq-regulatory",
                description="Regulatory citation coverage",
            ),
        ),
    )


SERBIA_INITIAL_STATUSES: dict[str, SufficiencyStatus] = {
    "in-market-size": SufficiencyStatus.MISSING,
    "in-market-maturity": SufficiencyStatus.SUFFICIENT,
    "in-horeca-demand": SufficiencyStatus.SUFFICIENT,
    "in-competitors": SufficiencyStatus.SUFFICIENT,
    "in-channels": SufficiencyStatus.SUFFICIENT,
    "in-pricing": SufficiencyStatus.SUFFICIENT,
    "in-geography": SufficiencyStatus.SUFFICIENT,
    "in-regulatory-coverage": SufficiencyStatus.INSUFFICIENT,
}


class EvidenceProgressionEvaluator:
    """
    Evidence-aware sufficiency evaluator for offline acceptance replay.

    Needs become SUFFICIENT only when run-scoped evidence explicitly references
    their information_need_id. Stuck needs never improve.
    """

    def __init__(
        self,
        *,
        design: ResearchDesign,
        initial_statuses: dict[str, SufficiencyStatus],
        improvable_needs: frozenset[str],
        stuck_needs: frozenset[str] = frozenset(),
    ) -> None:
        self._design = design
        self._initial_statuses = dict(initial_statuses)
        self._improvable_needs = improvable_needs
        self._stuck_needs = stuck_needs
        self.calls = 0

    def evaluate(
        self,
        *,
        design: ResearchDesign,
        evidence: Sequence[Evidence],
    ) -> ResearchReadinessResult:
        self.calls += 1
        assessments: list[InformationNeedAssessment] = []
        for need in design.information_needs:
            has_targeted_evidence = any(
                need.id in item.information_need_refs
                and not item.id.startswith("initial-")
                for item in evidence
            )
            if need.id in self._stuck_needs:
                status = self._initial_statuses[need.id]
            elif has_targeted_evidence and need.id in self._improvable_needs:
                status = SufficiencyStatus.SUFFICIENT
            else:
                status = self._initial_statuses.get(
                    need.id,
                    SufficiencyStatus.MISSING,
                )
            assessments.append(
                need_assessment(
                    need_id=need.id,
                    rq_id=need.research_question_id,
                    status=status,
                ),
            )
        result = result_for_needs(*assessments)
        _store_completed_assessments(design, evidence, result)
        return result


class FakeSemanticSufficiencyAssessor:
    """Offline semantic assessor that records sufficiency-stage budget usage."""

    def __init__(
        self,
        *,
        status_by_need: dict[str, SufficiencyStatus],
    ) -> None:
        self._status_by_need = status_by_need
        self.calls = 0

    def assess(
        self,
        *,
        research_question: ResearchQuestion,
        information_need: InformationNeed,
        evidence: Sequence[Evidence],
        deterministic_signals: DeterministicSufficiencySignals,
    ) -> SemanticSufficiencyAssessment:
        self.calls += 1
        budget = get_execution_budget()
        if budget is not None:
            set_execution_stage("sufficiency")
            budget.assert_can_call("sufficiency")
            budget.record_llm_call("sufficiency")

        if deterministic_signals.evidence_count == 0:
            status = SufficiencyStatus.MISSING
            gap_types = (GapType.NO_EVIDENCE,)
        else:
            status = self._status_by_need.get(
                information_need.id,
                SufficiencyStatus.SUFFICIENT,
            )
            gap_types = ()
            if status == SufficiencyStatus.BLOCKED:
                gap_types = (GapType.UNRESOLVABLE,)
            elif status in {
                SufficiencyStatus.PARTIAL,
                SufficiencyStatus.INSUFFICIENT,
            }:
                gap_types = (GapType.INSUFFICIENT_DEPTH,)

        return SemanticSufficiencyAssessment(
            status=status,
            gap_types=gap_types,
            search_directives=("semantic directive",) if status != SufficiencyStatus.SUFFICIENT else (),
            reason=f"Fake semantic status={status.value}",
        )


class RecordingTargetedRunner:
    def __init__(
        self,
        *,
        source_repository: InMemorySourceRepository,
        evidence_repository: InMemoryEvidenceRepository,
        crash_before_need_id: str | None = None,
    ) -> None:
        self.calls = 0
        self.targeted_need_ids: list[str] = []
        self._inner = DeterministicTargetedResearchRunner(
            source_repository=source_repository,
            evidence_repository=evidence_repository,
        )
        self._crash_before_need_id = crash_before_need_id

    def run(
        self,
        context: WorkflowContext,
        request: TargetedResearchRequest,
    ):
        self.calls += 1
        self.targeted_need_ids.append(request.information_need_id)
        if (
            self._crash_before_need_id is not None
            and request.information_need_id == self._crash_before_need_id
        ):
            raise RuntimeError(
                f"simulated crash before provider work for {request.information_need_id}",
            )
        return self._inner.run(context, request)


class RecordingAnalysisService:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_for_context(self, context: WorkflowContext):
        self.calls += 1
        from application.analysis.analysis_service import AnalysisSummary

        return AnalysisSummary(
            finding_ids=(),
            insight_ids=(),
            evidence_batches_processed=0,
            finding_candidates_rejected=0,
            insight_candidates_rejected=0,
            batch_failures=0,
        )


class PassThroughExecutor(BaseExecutor):
    def run(self, context: WorkflowContext) -> WorkflowContext:
        return context


def build_readiness_service(
    evaluator,
    *,
    source_repository: InMemorySourceRepository | None = None,
    evidence_repository: InMemoryEvidenceRepository | None = None,
    runner=None,
    max_rounds: int = 2,
    max_attempts_per_gap: int = 2,
) -> ResearchReadinessService:
    source_repo = source_repository or InMemorySourceRepository()
    evidence_repo = evidence_repository or InMemoryEvidenceRepository()
    bounds = TargetedResearchBounds(
        max_gap_rounds_per_run=max_rounds,
        max_attempts_per_gap=max_attempts_per_gap,
        max_queries_per_gap=2,
        max_sources_per_gap=3,
    )
    runner = runner or DeterministicTargetedResearchRunner(
        source_repository=source_repo,
        evidence_repository=evidence_repo,
    )
    loop_service = ResearchLoopService(
        runner=runner,
        bounds=bounds,
        evaluator=evaluator,
        evidence_repository=evidence_repo,
        source_repository=source_repo,
    )
    return ResearchReadinessService(
        evaluator=evaluator,
        evidence_repository=evidence_repo,
        loop_service=loop_service,
    )


def workflow_context_for_design(design: ResearchDesign) -> WorkflowContext:
    project = Project(id="project-acceptance", name="P1 Acceptance")
    template = ResearchDesignWorkflowMapper().from_research_design(design, project)
    definition_ids = [task.id for task in template.task_definitions]
    task_by_def = {task.id: task for task in template.task_definitions}
    tasks = [
        make_task(
            definition_id,
            depends_on=list(task_by_def[definition_id].depends_on),
            executor_id=task_by_def[definition_id].executor_id,
        )
        for definition_id in definition_ids
    ]
    workflow_run = make_workflow_run(*tasks, template_id=template.id)
    return WorkflowContext(
        project=project,
        workflow_template=template,
        workflow_run=workflow_run,
    )


def seed_initial_status_evidence(
    repository: InMemoryEvidenceRepository,
    context: WorkflowContext,
    statuses: dict[str, SufficiencyStatus],
) -> None:
    """Make non-MISSING acceptance statuses honest durable assessments."""
    design = context.workflow_template.research_design_snapshot
    need_by_id = {need.id: need for need in design.information_needs}
    for need_id, status in statuses.items():
        if status == SufficiencyStatus.MISSING:
            continue
        need = need_by_id[need_id]
        repository.create(
            Evidence(
                id=f"initial-{need_id}",
                project_id=context.project.id,
                source_id=f"initial-source-{need_id}",
                source_content_checksum=f"initial-checksum-{need_id}",
                workflow_run_id=context.workflow_run.id,
                research_design_id=design.id,
                statement=f"Initial support for {need_id}",
                source_excerpt=f"Initial excerpt for {need_id}",
                created_at="2026-01-01T00:00:00+00:00",
                research_question_refs=(need.research_question_id,),
                information_need_refs=(need_id,),
                deduplication_key=f"initial-{need_id}",
            ),
        )


def run_rqcl_workflow(
    context: WorkflowContext,
    *,
    readiness_service: ResearchReadinessService,
    analysis_service: RecordingAnalysisService | None = None,
) -> tuple[RecordingAnalysisService, WorkflowContext]:
    analysis = analysis_service or RecordingAnalysisService()
    ensure_run_budget(context)
    set_execution_stage(stage_for_executor("research_quality"))
    readiness = ResearchReadinessExecutor(research_readiness_service=readiness_service)
    analysis_executor = AnalysisExecutor(analysis_service=analysis)
    resolver = Mock()
    resolver.resolve.side_effect = lambda task: {
        "search": PassThroughExecutor(),
        "evidence": PassThroughExecutor(),
        "research_quality": readiness,
        "analysis": analysis_executor,
        "report": PassThroughExecutor(),
        "review": PassThroughExecutor(),
    }[task.executor_id]
    engine = WorkflowEngine(
        scheduler=TaskScheduler(),
        task_executor=TaskExecutor(resolver=resolver, lifecycle=TaskLifecycleManager()),
        completion_policy=WorkflowCompletionPolicy(),
    )
    engine.run(context)
    finalize_run_budget(context)
    return analysis, context


def task_statuses(context: WorkflowContext) -> dict[str, TaskStatus]:
    return {task.definition_id: task.status for task in context.workflow_run.tasks}


def capture_results_dto(context: WorkflowContext) -> dict[str, Any]:
    """Build observability fields matching GET /workflow-runs/{id}/results."""
    readiness_task = next(
        task
        for task in context.workflow_run.tasks
        if task.definition_id == "task-assess-research-readiness"
    )
    task_results = {
        readiness_task.id: {
            "task_id": readiness_task.id,
            "definition_id": readiness_task.definition_id,
            "shared_state": dict(context.shared_state),
        },
    }
    readiness = extract_research_readiness(task_results)
    loop_state = context.read_shared(SHARED_LOOP_STATE_KEY) or {}
    loop_count = None
    loop_history = None
    if isinstance(readiness, dict):
        loop_count = readiness.get("research_loop_count")
        loop_history = readiness.get("research_loop_history")
    if isinstance(loop_state, dict):
        loop_count = loop_state.get("research_loop_count", loop_count)
        if loop_history is None:
            loop_history = loop_state.get("history")
    return {
        "run_id": context.workflow_run.id,
        "status": context.workflow_run.status.value,
        "is_terminal": context.workflow_run.is_terminal,
        "results_ready": context.workflow_run.is_terminal,
        "research_readiness": readiness,
        "research_loop_count": loop_count,
        "research_loop_history": loop_history,
    }


@dataclass
class P1AcceptanceScorecard:
    scenario: str
    initial_blockers: tuple[str, ...] = ()
    targeted_needs: tuple[str, ...] = ()
    rounds: int = 0
    targeted_iterations: int = 0
    new_sources: int = 0
    new_evidence: int = 0
    final_ready_for_analysis: bool = False
    final_research_outcome: str = ""
    termination_reason: str = ""
    analysis_calls: int = 0
    technical_failure: bool = False
    provider_fake_calls: int = 0
    repeated_completed_iterations: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_report(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "initial_blockers": list(self.initial_blockers),
            "targeted_needs": list(self.targeted_needs),
            "rounds": self.rounds,
            "targeted_iterations": self.targeted_iterations,
            "new_sources": self.new_sources,
            "new_evidence": self.new_evidence,
            "final_ready_for_analysis": self.final_ready_for_analysis,
            "final_research_outcome": self.final_research_outcome,
            "termination_reason": self.termination_reason,
            "analysis_calls": self.analysis_calls,
            "technical_failure": self.technical_failure,
            "provider_fake_calls": self.provider_fake_calls,
            "repeated_completed_iterations": self.repeated_completed_iterations,
            **self.extra,
        }


def build_scorecard(
    *,
    scenario: str,
    context: WorkflowContext,
    runner: RecordingTargetedRunner | None,
    analysis_calls: int,
    source_repo: InMemorySourceRepository,
    evidence_repo: InMemoryEvidenceRepository,
) -> P1AcceptanceScorecard:
    readiness = context.read_shared(SHARED_STATE_KEY) or {}
    loop_state = context.read_shared(SHARED_LOOP_STATE_KEY) or {}
    history = readiness.get("research_loop_history") or loop_state.get("history") or []
    targeted_needs: list[str] = []
    if runner is not None:
        targeted_needs = list(runner.targeted_need_ids)
    elif history:
        for record in history:
            targeted_needs.extend(record.get("targeted_need_ids", []))

    repeated = False
    if runner is not None:
        seen_completed: set[str] = set()
        for record in history:
            for need_id in record.get("targeted_need_ids", []):
                if need_id in seen_completed and targeted_needs.count(need_id) > 1:
                    repeated = True
                seen_completed.add(need_id)

    sources = source_repo.list_for_project(
        context.project.id,
        workflow_run_id=context.workflow_run.id,
    )
    evidence = evidence_repo.list_for_project(
        context.project.id,
        workflow_run_id=context.workflow_run.id,
    )
    return P1AcceptanceScorecard(
        scenario=scenario,
        initial_blockers=tuple(readiness.get("blocking_information_need_ids", ())),
        targeted_needs=tuple(targeted_needs),
        rounds=int(loop_state.get("current_round", 0) or 0),
        targeted_iterations=int(readiness.get("research_loop_count", 0) or 0),
        new_sources=len(sources),
        new_evidence=len(evidence),
        final_ready_for_analysis=bool(readiness.get("ready_for_analysis")),
        final_research_outcome=str(readiness.get("research_outcome", "")),
        termination_reason=str(
            readiness.get("research_loop_termination_reason")
            or readiness.get("termination_reason")
            or "",
        ),
        analysis_calls=analysis_calls,
        technical_failure=context.workflow_run.status == WorkflowStatus.FAILED,
        provider_fake_calls=runner.calls if runner is not None else 0,
        repeated_completed_iterations=repeated,
    )


def build_hybrid_evaluator(
    *,
    design: ResearchDesign,
    semantic_statuses: dict[str, SufficiencyStatus],
) -> tuple[HybridResearchSufficiencyEvaluator, FakeSemanticSufficiencyAssessor]:
    semantic = FakeSemanticSufficiencyAssessor(status_by_need=semantic_statuses)
    hybrid = HybridResearchSufficiencyEvaluator(
        deterministic_evaluator=DeterministicSufficiencyEvaluator(),
        semantic_assessor=semantic,
    )
    return hybrid, semantic
