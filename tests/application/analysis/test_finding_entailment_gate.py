"""P1-09.1 offline Finding ↔ Evidence entailment gate acceptance."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief

from application.analysis.analysis_service import AnalysisService
from application.analysis.exceptions import AnalysisError, FindingEntailmentError
from application.analysis.finding_entailment import (
    MAX_EVIDENCE_EXCERPT_CHARS,
    MAX_FINDING_STATEMENT_CHARS,
    EntailmentCandidateProjection,
    EntailmentEvidenceProjection,
    FindingEntailmentStatus,
    FindingEntailmentVerdict,
    ScriptedFindingEntailmentValidator,
    batch_entailment_candidates,
    parse_entailment_payload,
    project_entailment_candidate,
    ProvenanceValidFinding,
)
from application.execution.exceptions import BudgetExhaustedError
from application.ports.analysis_ports import (
    AnalysisInput,
    FindingCandidate,
    InsightCandidate,
)
from infrastructure.analysis.llm_finding_entailment_validator import (
    LlmFindingEntailmentValidator,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)
from tests.fixtures.p1_08_claim_grade_fixture import (
    DESIGN_ID,
    PROJECT_ID,
    claim_grade_brief,
    claim_grade_design,
    claim_grade_evidence,
)


def _design(*, design_id: str = "d1") -> ResearchDesign:
    return ResearchDesign(
        id=design_id,
        research_questions=(
            ResearchQuestion(
                id="rq-1",
                question="What changed in Brand A awareness?",
                objective_refs=("obj-1",),
                priority=1,
                rationale="",
            ),
        ),
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("synthesize",),
        deliverable_plan=("summary",),
        assumptions=(),
        limitations=(),
        language="en",
    )


def _evidence(
    *,
    evidence_id: str,
    statement: str,
    excerpt: str | None = None,
    project_id: str = "p1",
    workflow_run_id: str,
    research_design_id: str = "d1",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id=project_id,
        source_id=f"src-{evidence_id}",
        source_content_checksum=f"ck-{evidence_id}",
        workflow_run_id=workflow_run_id,
        research_design_id=research_design_id,
        statement=statement,
        source_excerpt=excerpt if excerpt is not None else statement,
        created_at="2026-08-11T00:00:00+00:00",
        research_question_refs=("rq-1",),
        evidence_type=EvidenceType.DIRECT_EXCERPT,
        deduplication_key=f"dedup-{evidence_id}",
    )


def _context(*, design: ResearchDesign, brief: ResearchBrief | None = None):
    from domain.factories.task_factory import TaskFactory
    from domain.factories.workflow_run_factory import WorkflowRunFactory
    from domain.project import Project
    from domain.value_objects.executor_type import ExecutorType
    from domain.workflow_template_builder import WorkflowTemplateBuilder
    from runtime.workflow_context import WorkflowContext

    template = (
        WorkflowTemplateBuilder(id="t1", name="T")
        .add_task(
            id="task-analyze",
            name="Analyze",
            executor_id="analysis",
            executor_type=ExecutorType.AGENT,
        )
        .build()
    )
    template.research_design_snapshot = design
    template.research_brief_snapshot = brief or ResearchBrief(
        title="T",
        business_question="Q",
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    return WorkflowContext(
        project=Project(id="p1", name="P"),
        workflow_run=run,
        workflow_template=template,
    )


class ScriptedFindingEngine:
    method_name = "test"

    def __init__(
        self,
        findings: list[FindingCandidate],
        *,
        insights_from_persisted: bool = True,
    ) -> None:
        self._findings = findings
        self._insights_from_persisted = insights_from_persisted
        self.insight_inputs: list[AnalysisInput] = []

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        return list(self._findings)

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        self.insight_inputs.append(analysis_input)
        if not self._insights_from_persisted:
            return []
        finding_refs = tuple(item.id for item in analysis_input.persisted_findings)
        if not finding_refs:
            return []
        return [
            InsightCandidate(
                statement="Insight from supported findings",
                implication="Implication",
                finding_refs=finding_refs,
                research_question_refs=("rq-1",),
            ),
        ]


def _service(
    *,
    engine: ScriptedFindingEngine,
    evidence_repo: InMemoryEvidenceRepository,
    finding_repo: InMemoryFindingRepository | None = None,
    insight_repo: InMemoryInsightRepository | None = None,
    validator: Any,
    max_entailment_candidates_per_batch: int | None = None,
    max_entailment_chars_per_batch: int | None = None,
) -> tuple[AnalysisService, InMemoryFindingRepository, InMemoryInsightRepository]:
    finding_repo = finding_repo or InMemoryFindingRepository()
    insight_repo = insight_repo or InMemoryInsightRepository()
    service = AnalysisService(
        analysis_engine=engine,
        evidence_repository=evidence_repo,
        finding_repository=finding_repo,
        insight_repository=insight_repo,
        max_evidence_per_batch=20,
        max_chars_per_batch=12000,
        finding_entailment_validator=validator,
        max_entailment_candidates_per_batch=max_entailment_candidates_per_batch,
        max_entailment_chars_per_batch=max_entailment_chars_per_batch,
    )
    return service, finding_repo, insight_repo


class FindingEntailmentGateTests(unittest.TestCase):
    def test_case_01_direct_support_persists(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-2024",
                statement="In 2024 aided awareness was 41%.",
                workflow_run_id=run_id,
            ),
        )
        evidence_repo.create(
            _evidence(
                evidence_id="ev-2025",
                statement="In 2025 aided awareness was 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Aided awareness increased by 7 percentage points.",
                    rationale="48% - 41% = 7pp",
                    evidence_refs=("ev-2024", "ev-2025"),
                    research_question_refs=("rq-1",),
                    finding_type=FindingType.SYNTHESIS.value,
                ),
            ],
        )
        validator = ScriptedFindingEntailmentValidator(
            status_by_id={"fc-0001": FindingEntailmentStatus.SUPPORTED},
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=validator,
        )
        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertEqual(
            finding_repo.get_by_id(summary.finding_ids[0]).statement,
            "Aided awareness increased by 7 percentage points.",
        )
        self.assertEqual(validator.calls[0][0].evidence[0].statement.startswith("In 2024"), True)

    def test_case_02_multi_evidence_synthesis_persists(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-aided",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        evidence_repo.create(
            _evidence(
                evidence_id="ev-unaided",
                statement="Unaided awareness rose from 18% to 23%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Brand awareness improved year over year.",
                    rationale="Both aided and unaided measures rose.",
                    evidence_refs=("ev-aided", "ev-unaided"),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(),
        )
        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertIn("improved", finding_repo.get_by_id(summary.finding_ids[0]).statement)

    def test_case_03_overstatement_rejected(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-aided",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement=(
                        "Brand A became the market leader across all customer segments."
                    ),
                    rationale="Awareness rose.",
                    evidence_refs=("ev-aided",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, insight_repo = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.UNSUPPORTED},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])
        self.assertEqual(insight_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_04_contradiction_rejected(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness fell from 48% to 41%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Upward trend.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.CONTRADICTED},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_05_unrelated_valid_refs_rejected(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Brand A awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Brand A's distribution coverage expanded nationally.",
                    rationale="Network growth.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.UNSUPPORTED},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_06_insufficient_support_rejected(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Some market commentary mentions Brand A.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement=(
                        "Brand A aided awareness increased by exactly 7 percentage points."
                    ),
                    rationale="Strong quantitative claim.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.INSUFFICIENT_EVIDENCE},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_07_conflicting_evidence_not_supported(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-a",
                statement="Source A: aided awareness rose to 48%.",
                workflow_run_id=run_id,
            ),
        )
        evidence_repo.create(
            _evidence(
                evidence_id="ev-b",
                statement="Source B: aided awareness fell to 35%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Aided awareness rose to 48%.",
                    rationale="Ignoring conflict.",
                    evidence_refs=("ev-a", "ev-b"),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.CONTRADICTED},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_08_partial_rejected(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness rose and Brand A leads all segments.",
                    rationale="Mixed claim.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.PARTIAL},
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_09_missing_evidence_ref_provenance_before_semantic(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Missing ref.",
                    evidence_refs=(),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        validator = ScriptedFindingEntailmentValidator()
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=validator,
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(validator.calls, [])
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_10_foreign_evidence_ref_provenance_before_semantic(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Foreign ref.",
                    evidence_refs=("ev-foreign",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        validator = ScriptedFindingEntailmentValidator()
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=validator,
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(validator.calls, [])
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_11_malformed_validator_output_fail_closed(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased by 7pp.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                raw_payload_by_call=[{"not_verdicts": []}],
            ),
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(context)
        self.assertIn("entailment", str(ctx.exception).lower())
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_12_unknown_candidate_id_fail_closed(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                raw_payload_by_call=[
                    {
                        "verdicts": [
                            {
                                "candidate_id": "fc-9999",
                                "status": "SUPPORTED",
                                "supported_evidence_ids": ["ev-1"],
                                "unsupported_claim_parts": [],
                                "rationale": "bad",
                            },
                        ],
                    },
                ],
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_13_missing_verdict_fail_closed(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        for eid, stmt in (
            ("ev-1", "Aided rose."),
            ("ev-2", "Unaided rose."),
        ):
            evidence_repo.create(
                _evidence(evidence_id=eid, statement=stmt, workflow_run_id=run_id),
            )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Aided increased.",
                    rationale="A",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
                FindingCandidate(
                    statement="Unaided increased.",
                    rationale="B",
                    evidence_refs=("ev-2",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                raw_payload_by_call=[
                    {
                        "verdicts": [
                            {
                                "candidate_id": "fc-0001",
                                "status": "SUPPORTED",
                                "supported_evidence_ids": ["ev-1"],
                                "unsupported_claim_parts": [],
                                "rationale": "ok",
                            },
                        ],
                    },
                ],
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_14_foreign_supported_evidence_id_fail_closed(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        evidence_repo.create(
            _evidence(
                evidence_id="ev-2",
                statement="Other fact.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                raw_payload_by_call=[
                    {
                        "verdicts": [
                            {
                                "candidate_id": "fc-0001",
                                "status": "SUPPORTED",
                                "supported_evidence_ids": ["ev-2"],
                                "unsupported_claim_parts": [],
                                "rationale": "bad subset",
                            },
                        ],
                    },
                ],
            ),
        )
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_15_only_supported_persists_among_mixed(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Aided awareness increased by 7 percentage points.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
                FindingCandidate(
                    statement="Brand A became market leader across all segments.",
                    rationale="Overstated.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={
                    "fc-0001": FindingEntailmentStatus.SUPPORTED,
                    "fc-0002": FindingEntailmentStatus.UNSUPPORTED,
                },
            ),
        )
        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        persisted = finding_repo.list_for_project("p1", workflow_run_id=run_id)
        self.assertEqual(len(persisted), 1)
        self.assertIn("7 percentage points", persisted[0].statement)
        self.assertEqual(summary.entailment_diagnostics.entailment_accepted_count, 1)
        self.assertEqual(
            summary.entailment_diagnostics.rejected_by_status["UNSUPPORTED"],
            1,
        )

    def test_case_16_rejected_finding_cannot_feed_insight(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Aided awareness increased by 7 percentage points.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
                FindingCandidate(
                    statement="Brand A is market leader in all segments.",
                    rationale="Overstated.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, insight_repo = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={
                    "fc-0001": FindingEntailmentStatus.SUPPORTED,
                    "fc-0002": FindingEntailmentStatus.UNSUPPORTED,
                },
            ),
        )
        summary = service.analyze_for_context(context)
        insights = insight_repo.list_for_project("p1", workflow_run_id=run_id)
        self.assertEqual(len(insights), 1)
        self.assertEqual(set(insights[0].finding_refs), set(summary.finding_ids))
        persisted_ids = {item.id for item in finding_repo.list_for_project("p1", workflow_run_id=run_id)}
        self.assertEqual(set(insights[0].finding_refs), persisted_ids)
        insight_input = engine.insight_inputs[0]
        self.assertEqual(len(insight_input.persisted_findings), 1)

    def test_case_17_all_findings_rejected_analysis_error(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Market leadership across all segments.",
                    rationale="Overstated.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, insight_repo = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                status_by_id={"fc-0001": FindingEntailmentStatus.UNSUPPORTED},
            ),
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(context)
        self.assertIn("entailment", str(ctx.exception))
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])
        self.assertEqual(insight_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_18_long_evidence_bounded_input(self) -> None:
        long_excerpt = "X" * (MAX_EVIDENCE_EXCERPT_CHARS + 500)
        long_statement = "Y" * (MAX_FINDING_STATEMENT_CHARS + 100)
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Aided awareness rose from 41% to 48%.",
                excerpt=long_excerpt,
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement=long_statement,
                    rationale="Bounded.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        validator = ScriptedFindingEntailmentValidator()
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=validator,
        )
        # Truncated SUPPORTED is coerced to INSUFFICIENT → no persist.
        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)
        projection = validator.calls[0][0]
        self.assertTrue(projection.truncated)
        self.assertLessEqual(len(projection.statement), MAX_FINDING_STATEMENT_CHARS)
        self.assertLessEqual(
            len(projection.evidence[0].source_excerpt),
            MAX_EVIDENCE_EXCERPT_CHARS,
        )
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])

    def test_case_19_multiple_entailment_batches_each_candidate_once(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Aided awareness rose from 41% to 48%.",
                workflow_run_id=run_id,
            ),
        )
        findings = [
            FindingCandidate(
                statement=f"Aided awareness finding {index}.",
                rationale="Direct.",
                evidence_refs=("ev-1",),
                research_question_refs=("rq-1",),
            )
            for index in range(1, 5)
        ]
        engine = ScriptedFindingEngine(findings)
        validator = ScriptedFindingEntailmentValidator()
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=validator,
            max_entailment_candidates_per_batch=2,
        )
        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 4)
        self.assertEqual(len(validator.calls), 2)
        seen_ids = [item.candidate_id for batch in validator.calls for item in batch]
        self.assertEqual(seen_ids, ["fc-0001", "fc-0002", "fc-0003", "fc-0004"])
        self.assertEqual(len(finding_repo.list_for_project("p1", workflow_run_id=run_id)), 4)

    def test_case_20_budget_exhaustion_no_unvalidated_persist(self) -> None:
        design = _design()
        context = _context(design=design)
        run_id = context.workflow_run.id
        evidence_repo = InMemoryEvidenceRepository()
        evidence_repo.create(
            _evidence(
                evidence_id="ev-1",
                statement="Awareness rose.",
                workflow_run_id=run_id,
            ),
        )
        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement="Awareness increased.",
                    rationale="Direct.",
                    evidence_refs=("ev-1",),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        service, finding_repo, _ = _service(
            engine=engine,
            evidence_repo=evidence_repo,
            validator=ScriptedFindingEntailmentValidator(
                fail_with=BudgetExhaustedError("analysis_max_llm_calls", stage="analysis"),
            ),
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(context)
        self.assertIn("budget", str(ctx.exception).lower())
        self.assertEqual(finding_repo.list_for_project("p1", workflow_run_id=run_id), [])


class FindingEntailmentParseAndBatchUnitTests(unittest.TestCase):
    def test_parse_rejects_malformed_status(self) -> None:
        projection = EntailmentCandidateProjection(
            candidate_id="fc-0001",
            statement="s",
            rationale="r",
            evidence_refs=("ev-1",),
            research_question_text=None,
            evidence=(
                EntailmentEvidenceProjection(
                    id="ev-1",
                    statement="e",
                    source_excerpt="e",
                ),
            ),
        )
        with self.assertRaises(FindingEntailmentError):
            parse_entailment_payload(
                {
                    "verdicts": [
                        {
                            "candidate_id": "fc-0001",
                            "status": "MAYBE",
                            "supported_evidence_ids": [],
                            "unsupported_claim_parts": [],
                            "rationale": "x",
                        },
                    ],
                },
                submitted=[projection],
            )

    def test_batch_entailment_never_omits_candidates(self) -> None:
        projections = [
            EntailmentCandidateProjection(
                candidate_id=f"fc-{index:04d}",
                statement="s" * 100,
                rationale="r",
                evidence_refs=("ev-1",),
                research_question_text=None,
                evidence=(
                    EntailmentEvidenceProjection(
                        id="ev-1",
                        statement="e",
                        source_excerpt="e",
                    ),
                ),
            )
            for index in range(1, 6)
        ]
        batches = batch_entailment_candidates(
            projections,
            max_candidates_per_batch=2,
            max_chars_per_batch=10_000,
        )
        flat = [item.candidate_id for batch in batches for item in batch]
        self.assertEqual(flat, [f"fc-{i:04d}" for i in range(1, 6)])


class BrandAClaimGradeEntailmentRegressionTests(unittest.TestCase):
    def test_brand_a_supported_findings_remain_viable(self) -> None:
        design = claim_grade_design()
        brief = claim_grade_brief()
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.project import Project
        from domain.value_objects.executor_type import ExecutorType
        from domain.workflow_template_builder import WorkflowTemplateBuilder
        from runtime.workflow_context import WorkflowContext

        template = (
            WorkflowTemplateBuilder(id="t-claim", name="Claim")
            .add_task(
                id="task-analyze",
                name="Analyze",
                executor_id="analysis",
                executor_type=ExecutorType.AGENT,
            )
            .build()
        )
        template.research_design_snapshot = design
        template.research_brief_snapshot = brief
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        evidence_repo = InMemoryEvidenceRepository()
        for item in claim_grade_evidence(
            project_id=PROJECT_ID,
            workflow_run_id=run.id,
            research_design_id=DESIGN_ID,
        ):
            evidence_repo.create(item)

        engine = ScriptedFindingEngine(
            [
                FindingCandidate(
                    statement=(
                        "Brand A’s aided awareness increased by 7 percentage points "
                        "from 41% in 2024 to 48% in 2025."
                    ),
                    rationale="48-41=7",
                    evidence_refs=("ev-aided-2024", "ev-aided-2025"),
                    research_question_refs=("rq-1",),
                ),
                FindingCandidate(
                    statement=(
                        "Brand A’s unaided awareness increased by 5 percentage points "
                        "from 18% in 2024 to 23% in 2025."
                    ),
                    rationale="23-18=5",
                    evidence_refs=("ev-unaided",),
                    research_question_refs=("rq-1",),
                ),
                FindingCandidate(
                    statement=(
                        "Overall, Brand A awareness strengthened year-over-year, "
                        "with both aided (+7 pp) and unaided (+5 pp) measures rising."
                    ),
                    rationale="Both measures rose.",
                    evidence_refs=("ev-aided-2024", "ev-aided-2025", "ev-unaided"),
                    research_question_refs=("rq-1",),
                ),
            ],
        )
        validator = ScriptedFindingEntailmentValidator(
            status_by_id={
                "fc-0001": FindingEntailmentStatus.SUPPORTED,
                "fc-0002": FindingEntailmentStatus.SUPPORTED,
                "fc-0003": FindingEntailmentStatus.SUPPORTED,
            },
        )
        service = AnalysisService(
            analysis_engine=engine,
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=20,
            max_chars_per_batch=12000,
            finding_entailment_validator=validator,
        )
        context = WorkflowContext(
            project=Project(id=PROJECT_ID, name="Claim"),
            workflow_run=run,
            workflow_template=template,
        )
        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 3)
        self.assertEqual(summary.entailment_diagnostics.entailment_accepted_count, 3)
        # Validator saw Evidence bodies, not IDs only.
        first = validator.calls[0][0]
        self.assertTrue(any("41%" in ev.statement for ev in first.evidence))


class LlmFindingEntailmentValidatorUnitTests(unittest.TestCase):
    def test_llm_validator_parses_supported_verdict(self) -> None:
        mock = Mock()
        mock.generate.return_value = LLMResponse(
            content=(
                '{"verdicts":[{"candidate_id":"fc-0001","status":"SUPPORTED",'
                '"supported_evidence_ids":["ev-1"],"unsupported_claim_parts":[],'
                '"rationale":"direct"}]}'
            ),
        )
        validator = LlmFindingEntailmentValidator(llm_client=mock)
        projection = EntailmentCandidateProjection(
            candidate_id="fc-0001",
            statement="Awareness increased by 7pp.",
            rationale="Direct.",
            evidence_refs=("ev-1",),
            research_question_text="What changed?",
            evidence=(
                EntailmentEvidenceProjection(
                    id="ev-1",
                    statement="41% to 48%",
                    source_excerpt="41% to 48%",
                ),
            ),
        )
        verdicts = validator.validate_batch([projection])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].status, FindingEntailmentStatus.SUPPORTED)
        self.assertEqual(mock.generate.call_count, 1)
        user_payload = mock.generate.call_args.args[0].user
        self.assertIn("source_excerpt=", user_payload)
        self.assertIn("41% to 48%", user_payload)


if __name__ == "__main__":
    unittest.main()
