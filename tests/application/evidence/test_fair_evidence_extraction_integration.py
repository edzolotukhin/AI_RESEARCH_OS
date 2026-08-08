"""Integration tests for need-fair evidence extraction under budget caps."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    ensure_run_budget,
    set_execution_stage,
)
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from domain.evidence.evidence_type import EvidenceType
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import (
    InMemorySourceRepository,
)
from runtime.workflow_context import WorkflowContext


class _CallTrackingExtractor(EvidenceExtractor):
    method_name = "test"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        need_id = run_context.information_need_ids[0]
        self.calls.append((source.id, need_id))
        budget = _current_budget.get()
        if budget is not None:
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        excerpt = source.content_text[:20]
        return [
            EvidenceCandidate(
                statement=f"Evidence for {need_id}",
                source_excerpt=excerpt,
                evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                research_question_refs=run_context.research_question_ids,
                information_need_refs=(need_id,),
            ),
        ]


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ResearchQuestion(id="rq-3", question="Q3", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(id="IN1", research_question_id="rq-1", description="Need 1"),
            InformationNeed(id="IN2", research_question_id="rq-2", description="Need 2"),
            InformationNeed(id="IN3", research_question_id="rq-3", description="Need 3"),
        ),
    )


def _source(source_id: str, *, need_id: str, rq_id: str, content: str) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id=source_id,
        project_id="project-1",
        url=f"https://example.com/{source_id}",
        canonical_url=f"https://example.com/{source_id}",
        title=source_id,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=f"checksum-{source_id}",
        workflow_run_refs=("run-fair",),
        research_design_refs=("design-1",),
        information_need_refs=(need_id,),
        research_question_refs=(rq_id,),
        query_refs=(f"sq-{need_id}",),
        metadata={
            "discovery_records": [
                {
                    "workflow_run_id": "run-fair",
                    "research_design_id": "design-1",
                    "query_id": f"sq-{need_id}",
                    "information_need_id": need_id,
                    "research_question_id": rq_id,
                }
            ]
        },
        retrieved_at=now,
        version=1,
    )


class FairEvidenceExtractionIntegrationTests(unittest.TestCase):
    def test_tight_cap_gives_each_need_an_extraction_opportunity(self) -> None:
        design = _design()
        template = WorkflowTemplate(
            id="template-fair",
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
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-fair"
        context = WorkflowContext(
            project=Project(id="project-1", name="Project"),
            workflow_template=template,
            workflow_run=run,
        )
        context.current_task = run.tasks[0]

        source_repo = InMemorySourceRepository()
        evidence_repo = InMemoryEvidenceRepository()
        large = "L" * 200
        small = "S" * 20
        for item in (
            ("source-in1", "IN1", "rq-1", large),
            ("source-in2", "IN2", "rq-2", small),
            ("source-in3", "IN3", "rq-3", small),
        ):
            source_repo.create(_source(item[0], need_id=item[1], rq_id=item[2], content=item[3]))

        extractor = _CallTrackingExtractor()
        service = EvidenceExtractionService(
            evidence_extractor=extractor,
            evidence_repository=evidence_repo,
            source_repository=source_repo,
        )
        budget = ExecutionBudget(evidence_max_llm_calls=3, llm_max_calls_per_run=100)
        ensure_run_budget(context)
        context.execution_metadata["execution_budget"] = budget
        token = _current_budget.set(budget)
        set_execution_stage("evidence")
        self.addCleanup(_current_budget.reset, token)

        summary = service.extract_for_context(context)

        self.assertTrue(summary.evidence_stage_budget_exhausted)
        needs_called = {need for _, need in extractor.calls}
        self.assertIn("IN1", needs_called)
        self.assertIn("IN2", needs_called)
        self.assertIn("IN3", needs_called)
        self.assertEqual(budget.stage_calls("evidence"), 3)

        stored = evidence_repo.list_for_project("project-1", workflow_run_id="run-fair")
        need_refs = {item.information_need_refs[0] for item in stored}
        self.assertTrue({"IN1", "IN2", "IN3"}.issubset(need_refs))


if __name__ == "__main__":
    unittest.main()
