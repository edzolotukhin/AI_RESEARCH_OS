"""Report research-question coverage and structure validation tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

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
from application.report.exceptions import ReportError
from application.report.report_service import ReportService
from application.ports.report_ports import ReportSectionCandidate
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
        self.assertIn("RQ5", covered)

    def test_missing_rq_without_supporting_evidence_fails_explicitly(self) -> None:
        service = _deterministic_service(max_rq_correction_attempts=1)
        _seed_run_data(service, covered_questions={f"RQ{index}" for index in range(1, 6)})
        with self.assertRaises(ReportError) as ctx:
            service.write_for_context(_context())
        self.assertIn("RQ6", str(ctx.exception))
        self.assertIn("missing required research question coverage", str(ctx.exception))

    def test_provenance_and_citations_persist(self) -> None:
        service = _deterministic_service()
        _seed_run_data(service)
        summary = service.write_for_context(_context())
        report = service._report_repository.get_by_id(summary.report_id)
        assert report is not None
        for section in report.sections:
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
