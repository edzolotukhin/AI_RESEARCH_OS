"""PostgreSQL persistence contract for IR-2 recovery decisions."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.content_chunking import SourceContentChunk
from application.evidence.evidence_extraction_scheduler import (
    EvidenceExtractionWorkItem,
    PHASE_FIRST_OPPORTUNITY,
    extraction_retry_identity,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.sources.source_need_exhaustion import (
    completed_low_value_operation_ids,
    completed_low_value_source_need_identities,
    work_item_is_completed_low_value,
)
from application.config import ApplicationOverrides
from application.composition_root import create_application_container
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="ir2-recovery-design",
        research_questions=(ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),),
        information_needs=(
            InformationNeed(
                id="in-prerequisite",
                research_question_id="rq-1",
                description="Prerequisite evidence",
            ),
            InformationNeed(
                id="in-context",
                research_question_id="rq-1",
                description="Context evidence",
            ),
        ),
    )


def _source(*, revision: int = 1, checksum: str = "checksum-v1") -> Source:
    return Source(
        id="ir2-source-1",
        project_id="project",
        url="https://example.test/ir2-source",
        canonical_url="https://example.test/ir2-source",
        title="IR-2 source",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        retrieval_status=RetrievalStatus.TRUNCATED,
        content_text="bounded source content",
        content_checksum=checksum,
        content_revision=revision,
        extraction_revision="extract-v1",
        workflow_run_refs=("ir2-recovery-run",),
        research_design_refs=("ir2-recovery-design",),
        information_need_refs=("in-prerequisite", "in-context"),
        research_question_refs=("rq-1",),
        query_refs=("sq-in-prerequisite",),
        metadata={"truncated": True},
    )


def _attempt_item(
    *,
    operation_id: str,
    retry_identity: str,
    information_need_id: str = "in-prerequisite",
    source_id: str = "ir2-source-1",
    status: str = "success",
    categories: tuple[str, ...] = ("provenance_rejection",),
) -> dict:
    return {
        "source_id": source_id,
        "information_need_ids": [information_need_id],
        "primary_need_id": information_need_id,
        "extractor_status": status,
        "failure_categories": list(categories),
        "candidate_outcomes": [{"outcome": "rejected"}],
        "operation_id": operation_id,
        "source_retry_identity": retry_identity,
    }


class IR2SourceRecoveryPersistencePostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_recovery_diagnostics_reload_and_bound_identical_attempts(self) -> None:
        config = postgresql_application_config()
        container = create_application_container(
            config=config,
            overrides=ApplicationOverrides(),
        )

        project = container.project_service.create_project("IR2 recovery persistence")
        design = _design()
        template = ResearchDesignWorkflowMapper().from_research_design(design, project)
        container.workflow_service.publish_template_snapshot(
            template,
            project_id=project.id,
        )
        run = container.workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id="ir2-recovery-run",
        )

        source = _source()
        context = RunScopedSourceContext(
            workflow_run_id=run.id,
            research_design_id=design.id,
            information_need_ids=("in-prerequisite", "in-context"),
            research_question_ids=("rq-1",),
            query_ids=("sq-in-prerequisite",),
        )
        item = EvidenceExtractionWorkItem(
            source=source,
            chunk=SourceContentChunk("bounded source content", 0, 22),
            run_context=context,
            phase=PHASE_FIRST_OPPORTUNITY,
            source_first_attempt=True,
            primary_need_id="in-prerequisite",
        )
        operation_id = EvidenceExtractionService._work_item_operation_id(
            item,
            workflow_run_id=run.id,
        )
        retry_identity = extraction_retry_identity(source)

        completed = _attempt_item(
            operation_id=operation_id,
            retry_identity=retry_identity,
        )
        technical = _attempt_item(
            operation_id="ir2-technical",
            retry_identity=retry_identity,
            status="exception",
            categories=("provider_exception",),
        )
        budget = _attempt_item(
            operation_id="ir2-budget",
            retry_identity=retry_identity,
            status="budget_stop",
            categories=("budget_stop",),
        )
        shared_state = {
            "evidence_extraction": {
                "diagnostics": {"work_items": [completed, technical, budget]},
            },
            "research_loop_state": {
                "history": [{
                    "remediation_attempt_diagnostics": {
                        "recovery_outcome": "provenance_rejection",
                        "recovery_action": "alternate_source_or_explicit_correction",
                        "completed_low_value_attempts": [completed],
                    },
                }],
            },
        }

        def update(task_results):
            task_results["ir2-task-a"] = {"shared_state": shared_state}
            # A copied task snapshot must not create a second recovery attempt.
            task_results["ir2-task-b"] = {"shared_state": shared_state}
            return task_results, None

        try:
            container.workflow_service.atomic_update_task_results(run.id, update)
        finally:
            container.shutdown()

        fresh = create_application_container(
            config=config,
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        first_read = fresh.workflow_service.get_task_results(run.id)
        second_read = fresh.workflow_service.get_task_results(run.id)
        self.assertEqual(first_read, second_read)

        reloaded_shared = first_read["ir2-task-b"]["shared_state"]
        operation_ids = completed_low_value_operation_ids(reloaded_shared)
        self.assertEqual(operation_ids, {operation_id})
        self.assertEqual(
            completed_low_value_source_need_identities(reloaded_shared),
            {(source.id, "in-prerequisite", retry_identity)},
        )
        self.assertTrue(work_item_is_completed_low_value(completed))
        self.assertFalse(work_item_is_completed_low_value(technical))
        self.assertFalse(work_item_is_completed_low_value(budget))
        self.assertEqual(
            len(reloaded_shared["research_loop_state"]["history"]),
            1,
        )

        changed_revision = _source(revision=2, checksum="checksum-v2")
        changed_item = EvidenceExtractionWorkItem(
            source=changed_revision,
            chunk=item.chunk,
            run_context=context,
            phase=item.phase,
            source_first_attempt=True,
            primary_need_id=item.primary_need_id,
        )
        changed_operation_id = EvidenceExtractionService._work_item_operation_id(
            changed_item,
            workflow_run_id=run.id,
        )
        changed_in_item = _attempt_item(
            operation_id=changed_operation_id,
            retry_identity=extraction_retry_identity(changed_revision),
            information_need_id="in-context",
        )
        self.assertNotIn(
            changed_operation_id,
            completed_low_value_operation_ids({
                "evidence_extraction": {"diagnostics": {"work_items": [completed]}},
            }),
        )
        self.assertNotEqual(changed_in_item["operation_id"], operation_id)


if __name__ == "__main__":
    unittest.main()
