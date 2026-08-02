from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief

from application.analysis.analysis_service import AnalysisService
from application.analysis.deduplication import compute_finding_deduplication_key
from application.analysis.evidence_batching import batch_evidence_by_question
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


def _evidence(
    *,
    evidence_id: str,
    question_ids: tuple[str, ...],
    statement: str = "shared fact",
    workflow_run_id: str = "run1",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id="p1",
        source_id="s1",
        source_content_checksum="abc",
        workflow_run_id=workflow_run_id,
        research_design_id="d1",
        statement=statement,
        source_excerpt=statement,
        created_at="2026-01-01T00:00:00+00:00",
        research_question_refs=question_ids,
        evidence_type=EvidenceType.DIRECT_EXCERPT,
        deduplication_key=f"dedup-{evidence_id}",
    )


class EvidenceBatchingTests(unittest.TestCase):
    def test_groups_by_research_question(self) -> None:
        items = [
            _evidence(evidence_id="e1", question_ids=("rq-a",)),
            _evidence(evidence_id="e2", question_ids=("rq-b",)),
            _evidence(evidence_id="e3", question_ids=("rq-a",)),
        ]
        batches = batch_evidence_by_question(items, max_evidence_per_batch=10)
        self.assertEqual(len(batches), 2)

    def test_splits_large_batches(self) -> None:
        items = [
            _evidence(evidence_id=f"e{i}", question_ids=("rq-a",), statement=f"s{i}")
            for i in range(5)
        ]
        batches = batch_evidence_by_question(items, max_evidence_per_batch=2)
        self.assertEqual(len(batches), 3)

    def test_multi_question_evidence_appears_in_each_question_batch(self) -> None:
        shared = _evidence(evidence_id="e-shared", question_ids=("rq-a", "rq-b"))
        batches = batch_evidence_by_question([shared], max_evidence_per_batch=10)
        by_question = {question_id: batch for question_id, batch in batches}
        self.assertIn("rq-a", by_question)
        self.assertIn("rq-b", by_question)
        self.assertIn(shared, by_question["rq-a"])
        self.assertIn(shared, by_question["rq-b"])

    def test_identical_finding_semantics_deduplicate_across_batches(self) -> None:
        shared = _evidence(evidence_id="e-shared", question_ids=("rq-a", "rq-b"))
        key = compute_finding_deduplication_key(
            workflow_run_id="run1",
            statement="Shared analytical conclusion",
            evidence_refs=("e-shared",),
        )
        key_from_other_batch = compute_finding_deduplication_key(
            workflow_run_id="run1",
            statement="Shared analytical conclusion",
            evidence_refs=("e-shared",),
        )
        self.assertEqual(key, key_from_other_batch)


class SharedStatementAnalysisEngine:
    method_name = "test"

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        evidence_refs = tuple(sorted({item.id for item in analysis_input.evidence_batch}))
        return [
            FindingCandidate(
                statement="Shared analytical conclusion",
                rationale="Cross-question synthesis",
                evidence_refs=evidence_refs,
                research_question_refs=(
                    (analysis_input.batch_question_id,)
                    if analysis_input.batch_question_id
                    else ()
                ),
            ),
        ]

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        finding_refs = tuple(item.id for item in analysis_input.persisted_findings)
        return [
            InsightCandidate(
                statement="Insight",
                implication="Implication",
                finding_refs=finding_refs,
            ),
        ]


class MultiQuestionFindingDedupTests(unittest.TestCase):
    def test_repeated_batch_use_creates_one_finding_row(self) -> None:
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
                ResearchQuestion(
                    id="rq-b",
                    question="Question B",
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
        brief = ResearchBrief(
            title="T",
            business_question="Q",
        )

        service = AnalysisService(
            analysis_engine=SharedStatementAnalysisEngine(),
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
        shared = _evidence(
            evidence_id="e-shared",
            question_ids=("rq-a", "rq-b"),
            workflow_run_id=run.id,
        )
        evidence_repo.create(shared)
        context = WorkflowContext(
            project=Project(id="p1", name="P"),
            workflow_run=run,
            workflow_template=template,
        )

        summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertEqual(
            len(finding_repo.list_for_project("p1", workflow_run_id=run.id)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
