"""Live-shaped report regression with mocked LLM output."""

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
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.report.diagnostics import (
    REJECTION_CATEGORY_INVALID_FINDING_REF,
)
from application.report.exceptions import ReportError
from application.report.report_service import ReportService
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
from infrastructure.report.llm_report_engine import LlmReportEngine
from runtime.workflow_context import WorkflowContext

RUN_ID = "766e98ea-f2ed-4138-a393-d6ace13c2232"
PROJECT_ID = "project-766e98ea"
DESIGN_ID = "design-766e98ea"


def _live_design() -> ResearchDesign:
    questions = tuple(
        ResearchQuestion(
            id=f"rq-{index}",
            question=f"Research question {index}",
            objective_refs=(f"obj-{index}",),
            priority=index,
            rationale="",
        )
        for index in range(1, 6)
    )
    needs = tuple(
        InformationNeed(
            id=f"in-{index}",
            research_question_id=f"rq-{(index - 1) % 5 + 1}",
            description=f"Need {index}",
        )
        for index in range(1, 8)
    )
    return ResearchDesign(
        id=DESIGN_ID,
        research_questions=questions,
        information_needs=needs,
        source_strategy=("web",),
        analysis_plan=("synthesize",),
        deliverable_plan=(
            "Executive summary",
            "Market overview",
            "Competitive landscape",
            "Consumer trends",
            "Regulatory context",
            "Strategic implications",
            "Risks and limitations",
        ),
        assumptions=(),
        limitations=("Desk research only",),
        language="en",
    )


def _live_findings(*, run_id: str = RUN_ID) -> list[Finding]:
    findings: list[Finding] = []
    for index in range(1, 56):
        question_id = f"rq-{(index - 1) % 5 + 1}"
        findings.append(
            Finding(
                id=f"finding-{index:03d}",
                project_id=PROJECT_ID,
                workflow_run_id=run_id,
                research_design_id=DESIGN_ID,
                statement=f"Finding statement {index}",
                rationale=f"Rationale {index}",
                evidence_refs=(f"evidence-{index:03d}",),
                created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=(question_id,),
                finding_type=FindingType.SYNTHESIS,
                deduplication_key=f"dedup-finding-{index:03d}",
            ),
        )
    return findings


def _live_insights(*, run_id: str = RUN_ID) -> list[Insight]:
    insights: list[Insight] = []
    for index in range(1, 18):
        question_id = f"rq-{(index - 1) % 5 + 1}"
        finding_id = f"finding-{index:03d}"
        insights.append(
            Insight(
                id=f"insight-{index:03d}",
                project_id=PROJECT_ID,
                workflow_run_id=run_id,
                research_design_id=DESIGN_ID,
                statement=f"Insight statement {index}",
                implication=f"Implication {index}",
                finding_refs=(finding_id,),
                created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=(question_id,),
                deduplication_key=f"dedup-insight-{index:03d}",
            ),
        )
    return insights


def _live_evidence(*, run_id: str = RUN_ID) -> list[Evidence]:
    items: list[Evidence] = []
    for index in range(1, 56):
        question_id = f"rq-{(index - 1) % 5 + 1}"
        items.append(
            Evidence(
                id=f"evidence-{index:03d}",
                project_id=PROJECT_ID,
                source_id=f"source-{index:03d}",
                source_content_checksum=f"checksum-{index:03d}",
                workflow_run_id=run_id,
                research_design_id=DESIGN_ID,
                statement=f"Evidence {index}",
                source_excerpt=f"Excerpt {index}",
                created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=(question_id,),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key=f"dedup-evidence-{index:03d}",
            ),
        )
    return items


def _report_context(*, run_id: str = RUN_ID) -> WorkflowContext:
    design = _live_design()
    template = WorkflowTemplate(
        id="template-report-live",
        name="Desk",
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
            title="Serbia Desk Research",
            business_question="Market assessment for Serbia",
            deliverables=list(design.deliverable_plan),
            language="en",
        ),
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    run.id = run_id
    context = WorkflowContext(
        project=Project(id=PROJECT_ID, name="Live Project"),
        workflow_template=template,
        workflow_run=run,
    )
    context.current_task = run.tasks[0]
    return context


def _build_service(
    llm_client,
    *,
    max_sections: int = 10,
) -> ReportService:
    engine = LlmReportEngine(
        llm_client=llm_client,
        max_output_tokens=8192,
        reasoning_effort="minimal",
        max_sections=max_sections,
        max_findings_per_section=15,
        max_insights_per_section=8,
        structured_output_max_attempts=3,
    )
    return ReportService(
        report_engine=engine,
        finding_repository=InMemoryFindingRepository(),
        insight_repository=InMemoryInsightRepository(),
        evidence_repository=InMemoryEvidenceRepository(),
        source_repository=InMemorySourceRepository(),
        report_repository=InMemoryReportRepository(),
        artifact_repository=InMemoryArtifactRepository(),
        max_findings_per_batch=20,
        max_chars_per_batch=12000,
    )


def _seed_repositories(service: ReportService, *, run_id: str = RUN_ID) -> None:
    for item in _live_evidence(run_id=run_id):
        service._evidence_repository.create(item)
    for item in _live_findings(run_id=run_id):
        service._finding_repository.create(item)
    for item in _live_insights(run_id=run_id):
        service._insight_repository.create(item)


def _valid_sections_payload(*, finding_ids: list[str], insight_ids: list[str]) -> str:
    return json.dumps(
        {
            "sections": [
                {
                    "title": "Market overview",
                    "content": "Consolidated market overview section.",
                    "finding_refs": finding_ids[:3],
                    "insight_refs": insight_ids[:2],
                    "research_question_refs": ["rq-1"],
                    "evidence_refs": [],
                },
                {
                    "title": "Competitive landscape",
                    "content": "Consolidated competitive landscape section.",
                    "finding_refs": finding_ids[3:6],
                    "insight_refs": insight_ids[2:4],
                    "research_question_refs": ["rq-2"],
                    "evidence_refs": [],
                },
            ],
        },
    )


def _summary_payload() -> str:
    return json.dumps(
        {
            "title": "Serbia Desk Research Report",
            "executive_summary": "Executive summary for Serbia desk research.",
            "limitations": ["Desk research only"],
        },
    )


class ReportLiveShapeTests(unittest.TestCase):
    def test_a_valid_multi_section_report_persists(self) -> None:
        llm_client = Mock()

        def _generate(prompt, options=None):
            if "section_summaries:" in prompt.user:
                return LLMResponse(content=_summary_payload())
            return LLMResponse(
                content=_valid_sections_payload(
                    finding_ids=[f"finding-{index:03d}" for index in range(1, 8)],
                    insight_ids=[f"insight-{index:03d}" for index in range(1, 5)],
                ),
            )

        llm_client.generate.side_effect = _generate
        service = _build_service(llm_client)
        _seed_repositories(service)
        context = _report_context()

        summary = service.write_for_context(context)

        self.assertGreaterEqual(summary.section_count, 2)
        self.assertEqual(summary.batch_failures, 0)
        report = service._report_repository.get_by_id(summary.report_id)
        assert report is not None
        self.assertGreaterEqual(len(report.sections), 2)

    def test_b_malformed_json_then_correction_succeeds(self) -> None:
        llm_client = Mock()
        calls = {"count": 0}

        def _generate(prompt, options=None):
            calls["count"] += 1
            if "section_summaries:" in prompt.user:
                return LLMResponse(content=_summary_payload())
            if calls["count"] == 1:
                return LLMResponse(content='{"sections": [')
            return LLMResponse(
                content=_valid_sections_payload(
                    finding_ids=["finding-001", "finding-002"],
                    insight_ids=["insight-001"],
                ),
            )

        llm_client.generate.side_effect = _generate
        service = _build_service(llm_client)
        _seed_repositories(service)

        summary = service.write_for_context(_report_context())

        self.assertGreaterEqual(summary.section_count, 1)
        self.assertGreaterEqual(calls["count"], 3)

    def test_c_truncated_output_retries_with_compact_regeneration(self) -> None:
        llm_client = Mock()
        calls = {"count": 0}

        def _generate(prompt, options=None):
            calls["count"] += 1
            if "section_summaries:" in prompt.user:
                return LLMResponse(content=_summary_payload())
            if calls["count"] == 1:
                return LLMResponse(
                    content='{"sections":[{"title":"T","content":"Partial',
                    finish_reason="length",
                )
            return LLMResponse(
                content=_valid_sections_payload(
                    finding_ids=["finding-001"],
                    insight_ids=["insight-001"],
                ),
            )

        llm_client.generate.side_effect = _generate
        service = _build_service(llm_client)
        _seed_repositories(service)

        summary = service.write_for_context(_report_context())

        self.assertGreaterEqual(summary.section_count, 1)
        self.assertGreaterEqual(calls["count"], 3)

    def test_d_invalid_ref_rejects_one_candidate_preserves_valid_sections(self) -> None:
        llm_client = Mock()

        def _generate(prompt, options=None):
            if "section_summaries:" in prompt.user:
                return LLMResponse(content=_summary_payload())
            return LLMResponse(
                content=json.dumps(
                    {
                        "sections": [
                            {
                                "title": "Valid section",
                                "content": "Valid content",
                                "finding_refs": ["finding-001"],
                                "insight_refs": ["insight-001"],
                                "research_question_refs": ["rq-1"],
                                "evidence_refs": [],
                            },
                            {
                                "title": "Invalid section",
                                "content": "Bad refs",
                                "finding_refs": ["finding-does-not-exist"],
                                "insight_refs": [],
                                "research_question_refs": ["rq-1"],
                                "evidence_refs": [],
                            },
                        ],
                    },
                ),
            )

        llm_client.generate.side_effect = _generate
        service = _build_service(llm_client)
        _seed_repositories(service)

        summary = service.write_for_context(_report_context())

        self.assertEqual(summary.section_count, 1)
        self.assertEqual(summary.sections_rejected, 0)

    def test_e_all_invalid_sections_raises_with_diagnostics(self) -> None:
        llm_client = Mock()

        def _generate(prompt, options=None):
            return LLMResponse(
                content=json.dumps(
                    {
                        "sections": [
                            {
                                "title": "Invalid",
                                "content": "Bad refs",
                                "finding_refs": ["missing-finding"],
                                "insight_refs": [],
                                "research_question_refs": ["rq-1"],
                                "evidence_refs": [],
                            },
                        ],
                    },
                ),
            )

        llm_client.generate.side_effect = _generate
        service = _build_service(llm_client)
        _seed_repositories(service)

        with self.assertRaises(ReportError) as ctx:
            service.write_for_context(_report_context())

        message = str(ctx.exception)
        self.assertIn("finding_count=55", message)
        self.assertIn("insight_count=17", message)
        self.assertIn("total_engine_dropped", message)

    def test_f_consolidated_sections_respect_bounds(self) -> None:
        llm_client = Mock()
        sections = [
            {
                "title": f"Section {index}",
                "content": f"Content {index}",
                "finding_refs": [f"finding-{index:03d}"],
                "insight_refs": [f"insight-{index:03d}"],
                "research_question_refs": [f"rq-{(index - 1) % 5 + 1}"],
                "evidence_refs": [],
            }
            for index in range(1, 13)
        ]
        llm_client.generate.return_value = LLMResponse(
            content=json.dumps({"sections": sections}),
        )
        engine = LlmReportEngine(
            llm_client=llm_client,
            max_sections=8,
            max_findings_per_section=15,
            max_insights_per_section=8,
        )
        from application.ports.report_ports import ReportInput

        report_input = ReportInput(
            project_id=PROJECT_ID,
            workflow_run_id=RUN_ID,
            research_design_id=DESIGN_ID,
            brief=ResearchBrief(title="T", business_question="Q"),
            design=_live_design(),
            findings=tuple(_live_findings()),
            insights=tuple(_live_insights()),
            evidence_by_id={item.id: item for item in _live_evidence()},
            sources_by_id={},
            section_titles=tuple(_live_design().deliverable_plan),
        )

        candidates = engine.generate_sections(report_input)

        self.assertLessEqual(len(candidates), 8)
        self.assertGreaterEqual(len(candidates), 6)

    def test_engine_tracks_invalid_finding_ref_category(self) -> None:
        llm_client = Mock()
        llm_client.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "sections": [
                        {
                            "title": "Invalid",
                            "content": "Bad refs",
                            "finding_refs": ["missing-finding"],
                            "insight_refs": [],
                            "research_question_refs": [],
                            "evidence_refs": [],
                        },
                    ],
                },
            ),
        )
        engine = LlmReportEngine(llm_client=llm_client)
        from application.ports.report_ports import ReportInput

        report_input = ReportInput(
            project_id=PROJECT_ID,
            workflow_run_id=RUN_ID,
            research_design_id=DESIGN_ID,
            brief=ResearchBrief(title="T", business_question="Q"),
            design=_live_design(),
            findings=tuple(_live_findings()[:1]),
            insights=tuple(_live_insights()[:1]),
            evidence_by_id={item.id: item for item in _live_evidence()[:1]},
            sources_by_id={},
            section_titles=("Section",),
        )

        candidates = engine.generate_sections(report_input)
        stats = engine.last_section_batch_stats
        assert stats is not None
        self.assertEqual(candidates, ())
        self.assertGreater(
            stats.rejection_counts.get(REJECTION_CATEGORY_INVALID_FINDING_REF, 0),
            0,
        )


if __name__ == "__main__":
    unittest.main()
