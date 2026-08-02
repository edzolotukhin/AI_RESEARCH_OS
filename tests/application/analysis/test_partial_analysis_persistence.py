from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief

from application.analysis.analysis_service import AnalysisService
from application.analysis.exceptions import AnalysisError
from application.ports.analysis_ports import AnalysisInput, FindingCandidate, InsightCandidate
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)


class FindingsOnlyAnalysisEngine:
    method_name = "test"

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        evidence_refs = tuple(sorted({item.id for item in analysis_input.evidence_batch}))
        return [
            FindingCandidate(
                statement="Persisted finding before insight failure",
                rationale="Audit trail",
                evidence_refs=evidence_refs,
                finding_type=FindingType.SYNTHESIS.value,
            ),
        ]

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        return []


class PartialAnalysisPersistenceTests(unittest.TestCase):
    def test_findings_remain_durable_when_insight_generation_produces_none(self) -> None:
        evidence_repo = InMemoryEvidenceRepository()
        finding_repo = InMemoryFindingRepository()
        insight_repo = InMemoryInsightRepository()

        design = ResearchDesign(
            id="d1",
            research_questions=(
                ResearchQuestion(
                    id="rq-a",
                    question="Question A",
                    objective_refs=("obj-1",),
                    priority=1,
                    rationale="",
                ),
            ),
            information_needs=(),
            source_strategy=("web",),
            analysis_plan=("compare",),
            deliverable_plan=("summary",),
            assumptions=(),
            limitations=(),
            language="en",
        )
        brief = ResearchBrief(title="T", business_question="Q")

        service = AnalysisService(
            analysis_engine=FindingsOnlyAnalysisEngine(),
            evidence_repository=evidence_repo,
            finding_repository=finding_repo,
            insight_repository=insight_repo,
            max_evidence_per_batch=10,
            max_chars_per_batch=12000,
        )

        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.project import Project
        from domain.workflow_template_builder import WorkflowTemplateBuilder
        from domain.value_objects.executor_type import ExecutorType
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
        template.research_brief_snapshot = brief
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        evidence_repo.create(
            Evidence(
                id="evidence-1",
                project_id="p1",
                source_id="s1",
                source_content_checksum="abc",
                workflow_run_id=run.id,
                research_design_id="d1",
                statement="fact",
                source_excerpt="fact",
                created_at="2026-01-01T00:00:00+00:00",
                research_question_refs=("rq-a",),
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key="dedup-evidence-1",
            ),
        )

        context = WorkflowContext(
            project=Project(id="p1", name="P"),
            workflow_run=run,
            workflow_template=template,
        )

        with self.assertRaises(AnalysisError):
            service.analyze_for_context(context)

        persisted = finding_repo.list_for_project("p1", workflow_run_id=run.id)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].statement, "Persisted finding before insight failure")
        self.assertEqual(insight_repo.list_for_project("p1", workflow_run_id=run.id), [])


if __name__ == "__main__":
    unittest.main()
