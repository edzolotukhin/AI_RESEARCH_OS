"""Report research-question coverage and structure validation tests."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.report.coverage_validation import (
    covered_research_question_ids,
    enrich_research_question_refs,
    missing_research_question_ids,
)
from application.report.exceptions import InvalidReportProvenanceError, ReportError
from application.execution.exceptions import BudgetExhaustedError
from application.report.citation_registry import CitationRegistry
from application.report.coverage_contract import CONTRACT_KEY, CONTRACT_VERSION
from application.report.diagnostics import ReportBatchDiagnostics
from application.report.report_service import ReportService, _claim_scope_rule
from application.replay.desk_downstream_replay import REPLAY_KEY
from application.ports.report_ports import ReportCandidate, ReportSectionCandidate
from application.research_scope.authoritative_scope import SCOPE_KEY, SCOPE_VERSION
from infrastructure.persistence.memory.in_memory_artifact_repository import (
    InMemoryArtifactRepository,
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
from infrastructure.persistence.memory.in_memory_report_repository import (
    InMemoryReportRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.report.llm_report_engine import LlmReportEngine
from runtime.workflow_context import WorkflowContext

RUN_ID = "28718268-68c3-4304-9a31-a03fe5e43fa2"
PROJECT_ID = "project-coverage"
DESIGN_ID = "design-coverage"


def _design(*, question_count: int = 6) -> ResearchDesign:
    questions = tuple(
        ResearchQuestion(
            id=f"RQ{index}",
            question=f"Research question {index}",
            objective_refs=(f"obj-{index}",),
            priority=index,
            rationale="",
        )
        for index in range(1, question_count + 1)
    )
    return ResearchDesign(
        id=DESIGN_ID,
        research_questions=questions,
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("synthesize",),
        deliverable_plan=tuple(f"Section {index}" for index in range(1, question_count + 1)),
        assumptions=(),
        limitations=("Desk research only",),
        language="en",
    )


def _context(*, design: ResearchDesign | None = None) -> WorkflowContext:
    design = design or _design()
    template = WorkflowTemplate(
        id="template-coverage",
        name="Coverage",
        task_definitions=[
            TaskDefinition(
                id="task-write-report",
                name="Report",
                executor_id="report",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
        research_brief_snapshot=ResearchBrief(
            title="Coverage Test",
            business_question="Market assessment",
            deliverables=list(design.deliverable_plan),
            language="en",
        ),
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = RUN_ID
    context = WorkflowContext(
        project=Project(id=PROJECT_ID, name="Coverage Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _seed_run_data(
    service: ReportService,
    *,
    covered_questions: set[str] | None = None,
) -> None:
    covered_questions = covered_questions or {f"RQ{index}" for index in range(1, 7)}
    source = Source(
        id="source-1",
        project_id=PROJECT_ID,
        url="https://example.com",
        title="Source",
        canonical_url="https://example.com",
        retrieved_at="2026-08-05T00:00:00+00:00",
        source_type="web",
        workflow_run_refs=(RUN_ID,),
    )
    service._source_repository.create(source)
    for index in range(1, 11):
        question_id = f"RQ{((index - 1) % 6) + 1}"
        if question_id not in covered_questions:
            continue
        evidence_id = f"evidence-{index:03d}"
        service._evidence_repository.create(
            Evidence(
                id=evidence_id,
                project_id=PROJECT_ID,
                source_id=source.id,
                source_content_checksum=f"checksum-{index:03d}",
                workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID,
                statement=f"Evidence {index}",
                source_excerpt=f"Excerpt {index}",
                created_at="2026-08-05T00:00:00+00:00",
                research_question_refs=(question_id,),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key=f"dedup-evidence-{index:03d}",
            ),
        )
        finding_id = f"finding-{index:03d}"
        service._finding_repository.create(
            Finding(
                id=finding_id,
                project_id=PROJECT_ID,
                workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID,
                statement=f"Finding {index}",
                rationale=f"Rationale {index}",
                evidence_refs=(evidence_id,),
                created_at="2026-08-05T00:00:00+00:00",
                research_question_refs=(question_id,),
                finding_type=FindingType.SYNTHESIS,
                deduplication_key=f"dedup-finding-{index:03d}",
            ),
        )
        service._insight_repository.create(
            Insight(
                id=f"insight-{index:03d}",
                project_id=PROJECT_ID,
                workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID,
                statement=f"Insight {index}",
                implication=f"Implication {index}",
                finding_refs=(finding_id,),
                created_at="2026-08-05T00:00:00+00:00",
                research_question_refs=(question_id,),
                deduplication_key=f"dedup-insight-{index:03d}",
            ),
        )


    from tests.helpers.citation_fixtures import sources_for
    sources_for(service._evidence_repository.list_for_project(PROJECT_ID), service._source_repository)


def _deterministic_service(*, max_rq_correction_attempts: int = 2) -> ReportService:
    return ReportService(
        report_engine=DeterministicReportEngine(),
        finding_repository=InMemoryFindingRepository(),
        insight_repository=InMemoryInsightRepository(),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=InMemorySourceRepository(),
        report_repository=InMemoryReportRepository(),
        artifact_repository=InMemoryArtifactRepository(),
        max_findings_per_batch=20,
        max_chars_per_batch=12000,
        max_rq_correction_attempts=max_rq_correction_attempts,
    )


class ReportCoverageValidationTests(unittest.TestCase):
    def _repair_diagnostics_for_candidate(self, candidate: ReportSectionCandidate) -> dict:
        service = _deterministic_service(max_rq_correction_attempts=1)
        service._report_engine = Mock()
        service._report_engine.generate_sections.return_value = (candidate,)
        finding = SimpleNamespace(
            id="finding-rq5",
            evidence_refs=("evidence-rq5",),
            research_question_refs=("rq5_current_status",),
        )
        attempts = service._repair_limited_mandatory_coverage(
            validated_sections=[], section_batch_map={}, findings=[finding], insights=[],
            evidence_by_id={}, sources_by_id={}, findings_by_id={}, insights_by_id={},
            citation_registry=CitationRegistry(), brief=Mock(), design=Mock(),
            section_titles=(), project_id=PROJECT_ID, workflow_run_id=RUN_ID,
            research_design_id=DESIGN_ID, coverage_snapshot=None,
            mandatory_rq_findings={"rq5_current_status": ("finding-rq5",)},
            diagnostics=(
                "substantive_coverage_missing:rq5_current_status",
                "mandatory_rq_finding_binding_missing:rq5_current_status",
            ),
        )
        for attempt in attempts:
            attempt["post_validation_errors"] = [
                "substantive_coverage_missing:rq5_current_status",
                "mandatory_rq_finding_binding_missing:rq5_current_status",
            ]
        context = _context()
        context.write_shared("report_repair_diagnostics", {"version": 1, "attempts": attempts})
        return context.read_shared("report_repair_diagnostics")

    def _claim_scope_service(
        self,
        *,
        authoritative_scope: dict,
        generated_results: list[object],
    ) -> tuple[ReportService, Mock]:
        service = _deterministic_service()
        _seed_run_data(service, covered_questions={"RQ1"})
        for finding in service._finding_repository.list_for_project(
            PROJECT_ID, workflow_run_id=RUN_ID,
        ):
            finding.metadata[SCOPE_KEY] = dict(authoritative_scope)
        engine = Mock()
        engine.method_name = "bounded-test"
        engine.last_section_batch_stats = None
        engine.generate_sections.side_effect = generated_results
        engine.generate_executive_summary.return_value = ReportCandidate(
            title="Corrected report",
            executive_summary="Bounded summary.",
            sections=(),
            limitations=("Desk research only",),
        )
        service._report_engine = engine
        return service, engine

    @staticmethod
    def _scope_candidate(*, content: str, claim_scope: dict) -> ReportSectionCandidate:
        return ReportSectionCandidate(
            title="RQ1 section",
            content=content,
            research_question_refs=("RQ1",),
            finding_refs=("finding-001",),
            evidence_refs=("evidence-001",),
            metadata={"claim_scope": claim_scope},
        )

    def test_repair_diagnostics_identify_generator_invalid_binding(self) -> None:
        diagnostics = self._repair_diagnostics_for_candidate(
            ReportSectionCandidate(title="Invalid", content="Body"),
        )
        target = diagnostics["attempts"][0]["targets"][0]
        self.assertEqual(target["rq_id"], "rq5_current_status")
        self.assertEqual(target["finding_ids"], ["finding-rq5"])
        self.assertEqual(target["candidate_sections"][0]["research_question_refs"], [])
        self.assertEqual(target["candidate_sections"][0]["finding_refs"], [])
        self.assertEqual(diagnostics["attempts"][0]["post_merge"]["rq5_current_status"], [])
        self.assertEqual(
            diagnostics["attempts"][0]["targets"][0]["append_outcomes"],
            [{"category": "validate_section_candidate:empty_support"}],
        )

    def test_repair_diagnostics_identify_merge_loss(self) -> None:
        candidate = ReportSectionCandidate(
            title="Valid", content="Body",
            research_question_refs=("rq5_current_status",),
            finding_refs=("finding-rq5",),
        )
        service = _deterministic_service(max_rq_correction_attempts=1)
        service._report_engine = Mock()
        service._report_engine.generate_sections.return_value = (candidate,)
        finding = SimpleNamespace(
            id="finding-rq5", evidence_refs=("evidence-rq5",),
            research_question_refs=("rq5_current_status",),
        )
        def reject_and_record(*args, append_outcome=None, **kwargs):
            append_outcome["category"] = "append_rejected"
            return False

        with patch.object(service, "_append_validated_section", side_effect=reject_and_record):
            attempts = service._repair_limited_mandatory_coverage(
                validated_sections=[], section_batch_map={}, findings=[finding], insights=[],
                evidence_by_id={}, sources_by_id={}, findings_by_id={}, insights_by_id={},
                citation_registry=CitationRegistry(), brief=Mock(), design=Mock(),
                section_titles=(), project_id=PROJECT_ID, workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID, coverage_snapshot=None,
                mandatory_rq_findings={"rq5_current_status": ("finding-rq5",)},
                diagnostics=("mandatory_rq_finding_binding_missing:rq5_current_status",),
            )
        target = attempts[0]["targets"][0]
        self.assertEqual(target["candidate_sections"][0]["research_question_refs"], ["rq5_current_status"])
        self.assertEqual(target["candidate_sections"][0]["finding_refs"], ["finding-rq5"])
        self.assertEqual(attempts[0]["post_merge"]["rq5_current_status"], [])
        self.assertEqual(
            attempts[0]["targets"][0]["append_outcomes"],
            [{"category": "append_rejected"}],
        )

    def test_append_diagnostics_record_validation_rejection(self) -> None:
        service = _deterministic_service(max_rq_correction_attempts=1)
        outcome = {}
        with patch("application.report.report_service.validate_section_candidate") as validate:
            validate.side_effect = InvalidReportProvenanceError(
                "unknown finding finding-rq5",
                category="invalid_finding_ref",
            )
            result = service._append_validated_section(
                ReportSectionCandidate(title="Invalid", content="Body"),
                validated_sections=[], section_batch_map={}, batch_question_id="rq5_current_status",
                findings_by_id={}, insights_by_id={}, evidence_by_id={}, sources_by_id={},
                citation_registry=CitationRegistry(), project_id=PROJECT_ID, workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID, design=Mock(), batch_diag=ReportBatchDiagnostics(
                    batch_question_id="rq5_current_status", input_finding_count=0, input_insight_count=0,
                ), append_outcome=outcome,
            )
        self.assertFalse(result)
        self.assertEqual(outcome, {"category": "validate_section_candidate:invalid_finding_ref"})

    def test_append_diagnostics_record_bounded_scope_mismatch(self) -> None:
        service = _deterministic_service(max_rq_correction_attempts=1)
        outcome = {}
        with patch(
            "application.report.report_service.validate_claim_scope_with_diagnostics",
            return_value=(
                ("unsupported numeric scope: 42 %",),
                {"rule": "unsupported_numeric_scope", "anchor_category": "period"},
            ),
        ):
            result = service._append_validated_section(
                ReportSectionCandidate(title="Valid", content="Body", finding_refs=("finding-rq5",)),
                validated_sections=[], section_batch_map={}, batch_question_id="rq5_current_status",
                findings_by_id={"finding-rq5": SimpleNamespace(
                    evidence_refs=(), project_id=PROJECT_ID, workflow_run_id=RUN_ID,
                    research_design_id=DESIGN_ID, research_question_refs=("RQ1",),
                )}, insights_by_id={},
                evidence_by_id={}, sources_by_id={}, citation_registry=CitationRegistry(),
                project_id=PROJECT_ID, workflow_run_id=RUN_ID, research_design_id=DESIGN_ID,
                design=_design(question_count=1), batch_diag=ReportBatchDiagnostics(
                    batch_question_id="rq5_current_status", input_finding_count=1, input_insight_count=0,
                ), append_outcome=outcome,
            )
        self.assertFalse(result)
        self.assertEqual(outcome["category"], "claim_scope_rejection")
        self.assertEqual(outcome["rule"], "unsupported_numeric_scope")
        self.assertEqual(outcome["mismatch"]["rule"], "unsupported_numeric_scope")
        self.assertEqual(outcome["mismatch"]["anchor_category"], "period")

    def test_claim_scope_rejection_diagnostics_use_bounded_rule_codes(self) -> None:
        cases = {
            "Report claim broadens the supported scope: operators=['all'] unsupported_scope=['x']": "broadening_scope",
            "unsupported numeric value: 42": "unsupported_numeric_value",
            "unsupported numeric unit: 42 %": "unsupported_numeric_unit",
            "unsupported numeric scope: 42 %": "unsupported_numeric_scope",
            "unexpected validator result": "other_claim_scope",
        }
        for error, expected in cases.items():
            with self.subTest(error=error):
                self.assertEqual(_claim_scope_rule((error,)), expected)

    def test_enrich_research_question_refs_from_batch_and_findings(self) -> None:
        design = _design(question_count=2)
        finding = Finding(
            id="finding-1",
            project_id=PROJECT_ID,
            workflow_run_id=RUN_ID,
            research_design_id=DESIGN_ID,
            statement="Finding",
            rationale="Rationale",
            evidence_refs=("evidence-1",),
            created_at="2026-08-05T00:00:00+00:00",
            research_question_refs=("RQ1",),
            finding_type=FindingType.SYNTHESIS,
            deduplication_key="dedup-finding-1",
        )
        candidate = ReportSectionCandidate(
            title="Section",
            content="Content",
            research_question_refs=(),
            finding_refs=("finding-1",),
            insight_refs=(),
        )
        refs = enrich_research_question_refs(
            candidate,
            batch_question_id="RQ1",
            findings_by_id={"finding-1": finding},
            insights_by_id={},
            design=design,
        )
        self.assertEqual(refs, ("RQ1",))

    def test_all_rqs_covered_report_proceeds(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        summary = service.write_for_context(_context())
        report = service._report_repository.get_by_id(summary.report_id)
        assert report is not None
        covered = covered_research_question_ids(
            report.sections,
            findings=service._finding_repository.list_for_project(
                PROJECT_ID,
                workflow_run_id=RUN_ID,
            ),
            design=_design(),
        )
        self.assertEqual(covered, {f"RQ{index}" for index in range(1, 7)})
        contract = report.metadata[CONTRACT_KEY]
        self.assertEqual(contract["version"], CONTRACT_VERSION)
        self.assertEqual(contract["mode"], "complete")
        self.assertEqual(contract["required_rq_ids"], [f"RQ{i}" for i in range(1, 7)])
        self.assertEqual(contract["excluded_rq_ids"], [])

    def test_missing_rq_triggers_bounded_correction(self) -> None:
        llm_client = Mock()

        def _section_payload(question_id: str) -> dict:
            suffix = f"{int(question_id.replace('RQ', '')):03d}"
            return {
                "title": f"Section {question_id}",
                "content": f"Coverage for {question_id}.",
                "finding_refs": [f"finding-{suffix}"],
                "insight_refs": [f"insight-{suffix}"],
                "research_question_refs": [question_id],
                "evidence_refs": [f"evidence-{suffix}"],
            }

        def _generate(prompt, options=None):
            if "section_summaries:" in prompt.user:
                return LLMResponse(
                    content=json.dumps(
                        {
                            "title": "Coverage Test Report",
                            "executive_summary": "Executive summary.",
                            "limitations": ["Desk research only"],
                        },
                    ),
                )
            if "batch_research_question_id: RQ5" in prompt.user:
                return LLMResponse(
                    content=json.dumps(
                        {"sections": [_section_payload("RQ5")]},
                    ),
                )
            question_id = None
            for line in prompt.user.splitlines():
                if line.startswith("batch_research_question_id:"):
                    question_id = line.split(":", 1)[1].strip()
            if question_id and question_id != "RQ5":
                return LLMResponse(
                    content=json.dumps(
                        {"sections": [_section_payload(question_id)]},
                    ),
                )
            return LLMResponse(content='{"sections":[]}')

        service = ReportService(
            report_engine=LlmReportEngine(llm_client=llm_client, structured_output_max_attempts=1),
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=InMemorySourceRepository(),
            report_repository=InMemoryReportRepository(),
            artifact_repository=InMemoryArtifactRepository(),
            max_findings_per_batch=20,
            max_chars_per_batch=12000,
            max_rq_correction_attempts=2,
        )
        _seed_run_data(service)
        state = {"rq5_initial": True}

        def _generate_with_miss(prompt, options=None):
            if (
                state["rq5_initial"]
                and "batch_research_question_id: RQ5" in prompt.user
                and "CORRECTION REQUEST" not in prompt.user
            ):
                state["rq5_initial"] = False
                return LLMResponse(content='{"sections":[]}')
            return _generate(prompt, options=options)

        llm_client.generate.side_effect = _generate_with_miss
        context = _context()
        summary = service.write_for_context(context)
        report = service._report_repository.get_by_id(summary.report_id)
        assert report is not None
        covered = covered_research_question_ids(
            report.sections,
            findings=service._finding_repository.list_for_project(
                PROJECT_ID,
                workflow_run_id=RUN_ID,
            ),
            design=_design(),
        )
        self.assertIn("RQ5", covered)

    def test_missing_rq_without_supporting_evidence_fails_explicitly(self) -> None:
        service = _deterministic_service(max_rq_correction_attempts=1)
        _seed_run_data(service, covered_questions={f"RQ{index}" for index in range(1, 6)})
        with self.assertRaises(ReportError) as ctx:
            service.write_for_context(_context())
        self.assertIn("RQ6", str(ctx.exception))
        self.assertIn("Report coverage validation failed", str(ctx.exception))

    def test_early_report_failure_persists_bounded_entry_diagnostics(self) -> None:
        service = _deterministic_service()
        context = _context()
        context.workflow_template.research_design_snapshot = None

        with self.assertRaises(ReportError) as ctx:
            service.write_for_context(context)

        self.assertIn("missing research_design_snapshot", str(ctx.exception))
        diagnostics = context.read_shared("report_generation_diagnostics")
        self.assertEqual(
            diagnostics,
            {
                "version": 1,
                "phase": "entry",
                "status": "started",
                "workflow_run_id": RUN_ID,
            },
        )
        self.assertLess(len(json.dumps(diagnostics)), 512)
        self.assertNotIn("prompt", diagnostics)
        self.assertNotIn("prose", diagnostics)

    def test_normal_claim_scope_correction_repairs_production_failure_shapes(self) -> None:
        cases = (
            (
                "unsupported_year",
                {
                    "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
                    "metrics": [], "population_dimensions": [], "numeric_facts": [],
                },
                self._scope_candidate(
                    content="The supported period is 2025 and 2026.",
                    claim_scope={"version": SCOPE_VERSION, "periods": ["2025", "2026"]},
                ),
                self._scope_candidate(
                    content="The supported period is 2026.",
                    claim_scope={"version": SCOPE_VERSION, "periods": ["2026"]},
                ),
                "broadening_scope",
            ),
            (
                "unsupported_value",
                {
                    "version": SCOPE_VERSION, "geography": [], "periods": [],
                    "metrics": [], "population_dimensions": [],
                    "numeric_facts": [{"value": "42", "unit": "%"}],
                },
                self._scope_candidate(
                    content="The unsupported value is 10%.",
                    claim_scope={
                        "version": SCOPE_VERSION,
                        "numeric_facts": [{"value": "10", "unit": "%"}],
                    },
                ),
                self._scope_candidate(
                    content="The finding supports a bounded qualitative conclusion.",
                    claim_scope={"version": SCOPE_VERSION, "numeric_facts": []},
                ),
                "unsupported_numeric_value",
            ),
            (
                "unsupported_numeric_period",
                {
                    "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
                    "metrics": [], "population_dimensions": [],
                    "numeric_facts": [{"value": "42", "unit": "uah", "periods": []}],
                },
                self._scope_candidate(
                    content="The value is 42 UAH in 2026.",
                    claim_scope={
                        "version": SCOPE_VERSION, "periods": ["2026"],
                        "numeric_facts": [
                            {"value": "42", "unit": "uah", "periods": ["2026"]},
                        ],
                    },
                ),
                self._scope_candidate(
                    content="The supported value is 42 UAH.",
                    claim_scope={
                        "version": SCOPE_VERSION,
                        "numeric_facts": [
                            {"value": "42", "unit": "uah", "periods": []},
                        ],
                    },
                ),
                "unsupported_numeric_scope",
            ),
        )
        for name, authority, initial, corrected, expected_rule in cases:
            with self.subTest(case=name):
                service, engine = self._claim_scope_service(
                    authoritative_scope=authority,
                    generated_results=[(initial,), (corrected,)],
                )
                context = _context(design=_design(question_count=1))

                summary = service.write_for_context(context)

                self.assertIsNotNone(summary.report_id)
                self.assertEqual(engine.generate_sections.call_count, 2)
                correction = context.read_shared("report_generation_diagnostics")[
                    "claim_scope_corrections"
                ][0]
                self.assertEqual(correction["attempt"], 1)
                self.assertEqual(correction["status"], "corrected_and_accepted")
                self.assertEqual(
                    correction["original_rejections"][0]["rule"], expected_rule,
                )
                self.assertEqual(
                    correction["corrected_candidate_outcomes"][0]["category"],
                    "appended",
                )

    def test_normal_claim_scope_correction_is_bounded_and_fails_closed(self) -> None:
        authority = {
            "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
            "metrics": [], "population_dimensions": [], "numeric_facts": [],
        }
        invalid = self._scope_candidate(
            content="Unsupported period 2025.",
            claim_scope={"version": SCOPE_VERSION, "periods": ["2025"]},
        )
        service, engine = self._claim_scope_service(
            authoritative_scope=authority,
            generated_results=[(invalid,), (invalid,)],
        )
        context = _context(design=_design(question_count=1))

        with self.assertRaises(ReportError):
            service.write_for_context(context)

        self.assertEqual(engine.generate_sections.call_count, 2)
        correction = context.read_shared("report_generation_diagnostics")[
            "claim_scope_corrections"
        ][0]
        self.assertEqual(correction["attempt"], 1)
        self.assertEqual(correction["status"], "corrected_but_rejected")

    def test_normal_claim_scope_correction_records_budget_guard(self) -> None:
        authority = {
            "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
            "metrics": [], "population_dimensions": [], "numeric_facts": [],
        }
        invalid = self._scope_candidate(
            content="Unsupported period 2025.",
            claim_scope={"version": SCOPE_VERSION, "periods": ["2025"]},
        )
        service, engine = self._claim_scope_service(
            authoritative_scope=authority,
            generated_results=[
                (invalid,),
                BudgetExhaustedError("report_max_llm_calls", stage="report"),
            ],
        )
        context = _context(design=_design(question_count=1))

        with self.assertRaises(ReportError):
            service.write_for_context(context)

        self.assertEqual(engine.generate_sections.call_count, 2)
        correction = context.read_shared("report_generation_diagnostics")[
            "claim_scope_corrections"
        ][0]
        self.assertEqual(correction["status"], "correction_not_attempted_budget")

    def test_normal_claim_scope_correction_records_generation_failure(self) -> None:
        authority = {
            "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
            "metrics": [], "population_dimensions": [], "numeric_facts": [],
        }
        invalid = self._scope_candidate(
            content="Unsupported period 2025.",
            claim_scope={"version": SCOPE_VERSION, "periods": ["2025"]},
        )
        service, engine = self._claim_scope_service(
            authoritative_scope=authority,
            generated_results=[(invalid,), RuntimeError("provider detail must not persist")],
        )
        context = _context(design=_design(question_count=1))

        with self.assertRaises(ReportError):
            service.write_for_context(context)

        correction = context.read_shared("report_generation_diagnostics")[
            "claim_scope_corrections"
        ][0]
        self.assertEqual(correction["status"], "correction_generation_failed")
        self.assertNotIn("provider detail", str(correction))

    def test_cross_run_and_lineage_rejections_do_not_trigger_correction(self) -> None:
        authority = {
            "version": SCOPE_VERSION, "geography": [], "periods": ["2026"],
            "metrics": [], "population_dimensions": [], "numeric_facts": [],
        }
        candidate = self._scope_candidate(
            content="Supported period 2026.",
            claim_scope={"version": SCOPE_VERSION, "periods": ["2026"]},
        )
        for category in ("cross_run_ref", "cross_design_ref"):
            with self.subTest(category=category):
                service, engine = self._claim_scope_service(
                    authoritative_scope=authority,
                    generated_results=[(candidate,)],
                )
                context = _context(design=_design(question_count=1))

                with patch(
                    "application.report.report_service.validate_section_candidate",
                    side_effect=InvalidReportProvenanceError(
                        "invalid provenance", category=category,
                    ),
                ):
                    with self.assertRaises(ReportError):
                        service.write_for_context(context)

                self.assertEqual(engine.generate_sections.call_count, 1)
                diagnostics = context.read_shared("report_generation_diagnostics")
                self.assertNotIn("claim_scope_corrections", diagnostics)

    def test_normal_period_rejections_persist_after_zero_sections(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        context = _context()
        mismatch = {
            "rule": "unsupported_numeric_scope",
            "anchor_category": "period",
            "candidate_anchors": ["2025"],
            "supported_anchors": ["2026"],
        }

        with patch(
            "application.report.report_service.validate_claim_scope_with_diagnostics",
            return_value=(("unsupported numeric scope: 42 %",), mismatch),
        ):
            with self.assertRaises(ReportError) as raised:
                service.write_for_context(context)

        self.assertIn("No valid report sections produced", str(raised.exception))
        diagnostics = context.read_shared("report_generation_diagnostics")
        self.assertEqual(diagnostics["phase"], "candidate_validation")
        self.assertEqual(diagnostics["status"], "failed")
        self.assertEqual(diagnostics["valid_candidate_count"], 0)
        rejection = diagnostics["claim_scope_rejections"][0]
        self.assertEqual(rejection["category"], "claim_scope_rejection")
        self.assertEqual(rejection["rule"], "unsupported_numeric_scope")
        self.assertEqual(rejection["dimension"], "period")
        self.assertEqual(rejection["candidate_scope"], {"candidate_anchors": ["2025"]})
        self.assertEqual(rejection["supported_scope"], {"supported_anchors": ["2026"]})
        self.assertTrue(rejection["candidate_id"].startswith("candidate-"))
        self.assertTrue(rejection["finding_ids"])
        serialized = json.dumps(diagnostics)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("provider", serialized)
        self.assertNotIn("Report prose", serialized)

    def test_normal_numeric_and_unit_rejections_persist_bounded_scopes(self) -> None:
        cases = (
            (
                "unsupported numeric value: 99",
                {
                    "rule": "unsupported_numeric_value",
                    "candidate_value": "99",
                    "supported_values": ["42"],
                },
                "numeric_value",
                {"candidate_value": "99"},
                {"supported_values": ["42"]},
            ),
            (
                "unsupported numeric unit: 42 %",
                {
                    "rule": "unsupported_numeric_unit",
                    "candidate_value": "42",
                    "candidate_unit": "%",
                    "supported_units": ["uah"],
                },
                "unit",
                {"candidate_value": "42", "candidate_unit": "%"},
                {"supported_units": ["uah"]},
            ),
        )
        for error, mismatch, dimension, candidate_scope, supported_scope in cases:
            with self.subTest(rule=mismatch["rule"]):
                service = _deterministic_service()
                _seed_run_data(service)
                context = _context()
                with patch(
                    "application.report.report_service.validate_claim_scope_with_diagnostics",
                    return_value=((error,), mismatch),
                ):
                    with self.assertRaises(ReportError):
                        service.write_for_context(context)

                rejection = context.read_shared("report_generation_diagnostics")[
                    "claim_scope_rejections"
                ][0]
                self.assertEqual(rejection["rule"], mismatch["rule"])
                self.assertEqual(rejection["dimension"], dimension)
                self.assertEqual(rejection["candidate_scope"], candidate_scope)
                self.assertEqual(rejection["supported_scope"], supported_scope)

    def test_replay_normal_rejection_persists_replay_and_source_lineage(self) -> None:
        replay_run_id = "replay-run-coverage"
        service = _deterministic_service()
        _seed_run_data(service)
        context = _context()
        context.workflow_run.id = replay_run_id
        context.write_shared(REPLAY_KEY, {"source_workflow_run_id": RUN_ID})

        with patch(
            "application.report.report_service.validate_claim_scope_with_diagnostics",
            return_value=(
                ("unsupported numeric value: 99",),
                {
                    "rule": "unsupported_numeric_value",
                    "candidate_value": "99",
                    "supported_values": ["42"],
                },
            ),
        ):
            with self.assertRaises(ReportError):
                service.write_for_context(context)

        diagnostics = context.read_shared("report_generation_diagnostics")
        self.assertEqual(diagnostics["replay_run_id"], replay_run_id)
        self.assertEqual(diagnostics["source_run_id"], RUN_ID)
        rejection = diagnostics["claim_scope_rejections"][0]
        self.assertEqual(rejection["replay_run_id"], replay_run_id)
        self.assertEqual(rejection["source_run_id"], RUN_ID)

    def test_normal_rejection_diagnostics_keep_each_rule_correlated(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        context = _context()
        mismatch = {
            "rule": "broadening_scope",
            "dimension": "geography",
            "candidate_anchors": ["foreign"],
            "supported_anchors": ["supported"],
            "rejections": [
                {
                    "rule": "broadening_scope",
                    "dimension": "geography",
                    "candidate_anchors": ["foreign"],
                    "supported_anchors": ["supported"],
                },
                {
                    "rule": "unsupported_numeric_value",
                    "dimension": "numeric_value",
                    "candidate_value": "99",
                    "supported_values": ["42"],
                },
            ],
        }
        with patch(
            "application.report.report_service.validate_claim_scope_with_diagnostics",
            return_value=(
                (
                    "Report claim uses unsupported geography scope",
                    "unsupported numeric value: 99",
                ),
                mismatch,
            ),
        ):
            with self.assertRaises(ReportError):
                service.write_for_context(context)

        rejections = context.read_shared("report_generation_diagnostics")[
            "claim_scope_rejections"
        ]
        first, second = rejections[0], rejections[1]
        self.assertEqual((first["rule"], first["dimension"]), (
            "broadening_scope", "geography",
        ))
        self.assertEqual(first["candidate_scope"], {"candidate_anchors": ["foreign"]})
        self.assertEqual(first["supported_scope"], {"supported_anchors": ["supported"]})
        self.assertEqual((second["rule"], second["dimension"]), (
            "unsupported_numeric_value", "numeric_value",
        ))
        self.assertEqual(second["candidate_scope"], {"candidate_value": "99"})
        self.assertEqual(second["supported_scope"], {"supported_values": ["42"]})

    def test_valid_normal_candidate_has_no_rejection_diagnostic(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        context = _context()

        with patch.object(
            service._report_engine,
            "generate_sections",
            wraps=service._report_engine.generate_sections,
        ) as generate_sections:
            service.write_for_context(context)

        diagnostics = context.read_shared("report_generation_diagnostics")
        self.assertNotIn("claim_scope_rejections", diagnostics)
        self.assertNotIn("claim_scope_corrections", diagnostics)
        self.assertEqual(generate_sections.call_count, 6)

    def test_provenance_and_citations_persist(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        summary = service.write_for_context(_context())
        report = service._report_repository.get_by_id(summary.report_id)
        assert report is not None
        for section in report.sections:
            kind = (section.metadata or {}).get("section_kind")
            if kind in {"limitations", "contradictions"}:
                continue
            self.assertTrue(section.finding_refs or section.insight_refs)
            if section.evidence_refs:
                self.assertTrue(section.citation_ids)
        self.assertTrue(report.citation_registry)


class ReportCoverageMatrixTests(unittest.TestCase):
    """Simulated live-run shape: 6 RQs, partial LLM omission of research_question_refs."""

    def test_matrix_detects_llm_omitted_rq_refs(self) -> None:
        design = _design()
        findings = [
            Finding(
                id=f"finding-rq{index}",
                project_id=PROJECT_ID,
                workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID,
                statement=f"Finding for RQ{index}",
                rationale="",
                evidence_refs=(f"evidence-rq{index}",),
                created_at="2026-08-05T00:00:00+00:00",
                research_question_refs=(f"RQ{index}",),
                finding_type=FindingType.SYNTHESIS,
                deduplication_key=f"dedup-rq{index}",
            )
            for index in range(1, 7)
        ]
        from domain.reports.report_section import ReportSection

        sections = [
            ReportSection(
                id=f"section-rq{index}",
                title=f"Section RQ{index}",
                content=f"Content for RQ{index}",
                research_question_refs=(),  # LLM omitted refs
                finding_refs=(f"finding-rq{index}",),
                insight_refs=(),
                evidence_refs=(f"evidence-rq{index}",),
                citation_ids=(f"S{index}",),
            )
            for index in range(1, 7)
        ]
        missing = missing_research_question_ids(
            sections,
            findings=findings,
            design=design,
        )
        self.assertEqual(missing, ())


if __name__ == "__main__":
    unittest.main()
