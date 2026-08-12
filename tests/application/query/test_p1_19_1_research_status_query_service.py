"""P1-19.1 Research phase/status projection unit tests."""

from __future__ import annotations

import unittest

from application.query.research_status import ResearchExecutionStatus, ResearchPhase
from application.query.research_status_query_service import ResearchStatusQueryService
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _running(run) -> None:
    run.ready()
    run.start()


class ResearchStatusPhaseProjectionTests(unittest.TestCase):
    def test_case_03_planner_active_planning(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-plan",
                status=TaskStatus.RUNNING,
                executor_id="planner",
            ),
            run_id="r-plan",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.PLANNING,
        )

    def test_case_04_search_evidence_researching(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-collect-evidence",
                status=TaskStatus.RUNNING,
                executor_id="search",
            ),
            make_task(
                "task-extract-evidence",
                depends_on=["task-collect-evidence"],
                status=TaskStatus.CREATED,
                executor_id="evidence",
            ),
            run_id="r-search",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.RESEARCHING,
        )

    def test_case_05_readiness_evaluating(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-collect-evidence",
                status=TaskStatus.COMPLETED,
                executor_id="search",
            ),
            make_task(
                "task-extract-evidence",
                depends_on=["task-collect-evidence"],
                status=TaskStatus.COMPLETED,
                executor_id="evidence",
            ),
            make_task(
                "task-assess-research-readiness",
                depends_on=["task-extract-evidence"],
                status=TaskStatus.RUNNING,
                executor_id="research_quality",
            ),
            run_id="r-eval",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.EVALUATING,
        )

    def test_case_06_analysis_analyzing(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-analyze",
                status=TaskStatus.RUNNING,
                executor_id="analysis",
            ),
            run_id="r-an",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.ANALYZING,
        )

    def test_case_07_report_writing(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-analyze",
                status=TaskStatus.COMPLETED,
                executor_id="analysis",
            ),
            make_task(
                "task-write-report",
                depends_on=["task-analyze"],
                status=TaskStatus.RUNNING,
                executor_id="report",
            ),
            run_id="r-write",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.WRITING,
        )

    def test_case_08_review_reviewing(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-write-report",
                status=TaskStatus.COMPLETED,
                executor_id="report",
            ),
            make_task(
                "task-review-report",
                depends_on=["task-write-report"],
                status=TaskStatus.RUNNING,
                executor_id="review",
            ),
            run_id="r-rev",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.REVIEWING,
        )

    def test_precedence_review_over_completed_report(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-write-report",
                status=TaskStatus.COMPLETED,
                executor_id="report",
            ),
            make_task(
                "task-review-report",
                depends_on=["task-write-report"],
                status=TaskStatus.READY,
                executor_id="review",
            ),
            run_id="r-prec",
        )
        _running(run)
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.REVIEWING,
        )

    def test_terminal_phase_completed_even_if_failed(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-review-report",
                status=TaskStatus.FAILED,
                executor_id="review",
            ),
            run_id="r-term",
        )
        run.ready()
        run.start()
        run.fail()
        self.assertEqual(
            ResearchStatusQueryService.project_execution_status(run),
            ResearchExecutionStatus.TERMINAL,
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.COMPLETED,
        )
        self.assertEqual(run.status, WorkflowStatus.FAILED)

    def test_queued_created_run(self) -> None:
        run = make_workflow_run(
            make_task(
                "task-collect-evidence",
                status=TaskStatus.CREATED,
                executor_id="search",
            ),
            run_id="r-q",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_execution_status(run),
            ResearchExecutionStatus.QUEUED,
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.QUEUED,
        )

    def test_status_query_read_only_no_writes(self) -> None:
        from infrastructure.persistence.memory.in_memory_workflow_run_repository import (
            InMemoryWorkflowRunRepository,
        )

        repo = InMemoryWorkflowRunRepository()
        run = make_workflow_run(
            make_task(
                "task-collect-evidence",
                status=TaskStatus.CREATED,
                executor_id="search",
            ),
            run_id="r-ro",
        )
        run.project_id = "p1"
        repo.create(run, project_id="p1")

        class Guard:
            def __init__(self, inner):
                self._inner = inner
                self.writes = []

            def get_by_id(self, run_id):
                return self._inner.get_by_id(run_id)

            def get_task_results(self, run_id):
                return self._inner.get_task_results(run_id)

            def create(self, *a, **k):
                self.writes.append("create")
                raise AssertionError("write")

            def save(self, *a, **k):
                self.writes.append("save")
                raise AssertionError("write")

        guard = Guard(repo)
        service = ResearchStatusQueryService(workflow_run_repository=guard)
        status = service.get_status("r-ro")
        self.assertEqual(status.phase, ResearchPhase.QUEUED)
        self.assertEqual(guard.writes, [])


if __name__ == "__main__":
    unittest.main()
