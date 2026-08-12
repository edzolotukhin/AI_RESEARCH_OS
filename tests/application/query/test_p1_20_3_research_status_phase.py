"""P1-20.3 truthful Research phase projection."""

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


def _pipeline(
    *,
    collect=TaskStatus.WAITING,
    extract=TaskStatus.WAITING,
    assess=TaskStatus.WAITING,
    analyze=TaskStatus.WAITING,
    write=TaskStatus.WAITING,
    review=TaskStatus.WAITING,
    plan=None,
    run_id: str = "r-pipe",
):
    tasks = []
    if plan is not None:
        tasks.append(
            make_task("task-plan", status=plan, executor_id="planner"),
        )
    tasks.extend(
        [
            make_task(
                "task-collect-evidence",
                status=collect,
                executor_id="search",
                depends_on=["task-plan"] if plan is not None else None,
            ),
            make_task(
                "task-extract-evidence",
                depends_on=["task-collect-evidence"],
                status=extract,
                executor_id="evidence",
            ),
            make_task(
                "task-assess-research-readiness",
                depends_on=["task-extract-evidence"],
                status=assess,
                executor_id="research_quality",
            ),
            make_task(
                "task-analyze",
                depends_on=["task-assess-research-readiness"],
                status=analyze,
                executor_id="analysis",
            ),
            make_task(
                "task-write-report",
                depends_on=["task-analyze"],
                status=write,
                executor_id="report",
            ),
            make_task(
                "task-review-report",
                depends_on=["task-write-report"],
                status=review,
                executor_id="review",
            ),
        ]
    )
    run = make_workflow_run(*tasks, run_id=run_id)
    _running(run)
    return run


class TruthfulPhaseProjectionTests(unittest.TestCase):
    def test_case_03_planning_running_beats_waiting(self) -> None:
        run = _pipeline(plan=TaskStatus.RUNNING, run_id="r-plan-wait")
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.PLANNING,
        )

    def test_case_04_and_46_evidence_running_beats_review_waiting(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.RUNNING,
            run_id="r-ev-wait",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.RESEARCHING,
        )
        self.assertNotEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.REVIEWING,
        )

    def test_case_05_analysis_running_beats_review_waiting(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.COMPLETED,
            assess=TaskStatus.COMPLETED,
            analyze=TaskStatus.RUNNING,
            run_id="r-an-wait",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.ANALYZING,
        )

    def test_case_06_report_running_beats_review_waiting(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.COMPLETED,
            assess=TaskStatus.COMPLETED,
            analyze=TaskStatus.COMPLETED,
            write=TaskStatus.RUNNING,
            run_id="r-wr-wait",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.WRITING,
        )

    def test_case_07_review_running_reviewing(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.COMPLETED,
            assess=TaskStatus.COMPLETED,
            analyze=TaskStatus.COMPLETED,
            write=TaskStatus.COMPLETED,
            review=TaskStatus.RUNNING,
            run_id="r-rev-run",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.REVIEWING,
        )

    def test_case_08_ready_fallback_is_deterministic(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.COMPLETED,
            assess=TaskStatus.READY,
            run_id="r-ready",
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.EVALUATING,
        )

    def test_case_09_terminal_completed(self) -> None:
        run = _pipeline(
            collect=TaskStatus.COMPLETED,
            extract=TaskStatus.COMPLETED,
            assess=TaskStatus.COMPLETED,
            analyze=TaskStatus.SKIPPED,
            write=TaskStatus.SKIPPED,
            review=TaskStatus.SKIPPED,
            run_id="r-term-ok",
        )
        run.complete()
        self.assertEqual(
            ResearchStatusQueryService.project_execution_status(run),
            ResearchExecutionStatus.TERMINAL,
        )
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.COMPLETED,
        )
        self.assertEqual(run.status, WorkflowStatus.COMPLETED)

    def test_search_running_beats_review_waiting(self) -> None:
        run = _pipeline(collect=TaskStatus.RUNNING, run_id="r-search-wait")
        self.assertEqual(
            ResearchStatusQueryService.project_phase(run),
            ResearchPhase.RESEARCHING,
        )


if __name__ == "__main__":
    unittest.main()
