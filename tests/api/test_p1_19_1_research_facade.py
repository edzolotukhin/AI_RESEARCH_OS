"""P1-19.1 public Research API facade offline acceptance."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from application.persistence.records import ArtifactRecord
from application.query.research_run_result import ResearchRunOutcome
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.reports.report import Report
from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase, drain_background_runs
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class ResearchFacadeApiTests(ApiTestCase):
    def _seed_terminal_run(
        self,
        *,
        run_id: str,
        project_id: str,
        terminal: str,
        readiness: dict,
        tasks_factory,
        seed_entities=None,
    ) -> None:
        tasks = tasks_factory()
        run = make_workflow_run(*tasks, run_id=run_id)
        run.project_id = project_id
        run.ready()
        run.start()
        if terminal == "complete":
            run.complete()
        else:
            run.fail()
        repo = self.container.workflow_service._workflow_run_repository
        if repo.get_by_id(run_id) is None:
            repo.create(run, project_id=project_id)
            version = 0
        else:
            version = repo.get_version(run_id)
        readiness_task = next(
            task
            for task in run.tasks
            if task.definition_id == "task-assess-research-readiness"
        )
        task_results = {
            readiness_task.id: {
                "task_id": readiness_task.id,
                "definition_id": readiness_task.definition_id,
                "shared_state": {"research_readiness": readiness},
            },
            "_run_usage_summary": {
                "total_llm_calls": 3,
                "estimated_cost_usd": 0.1,
                "budget_exhausted": False,
                "stages": {},
            },
        }
        repo.save(run, expected_version=version, task_results=task_results)
        if seed_entities:
            seed_entities(project_id, run_id)

    def _pipeline(
        self,
        *,
        readiness=TaskStatus.COMPLETED,
        analyze=TaskStatus.COMPLETED,
        write=TaskStatus.COMPLETED,
        review=TaskStatus.COMPLETED,
    ):
        collect = make_task(
            "task-collect-evidence",
            status=TaskStatus.COMPLETED,
            executor_id="search",
            task_id="c1",
        )
        extract = make_task(
            "task-extract-evidence",
            depends_on=[collect.definition_id],
            status=TaskStatus.COMPLETED,
            executor_id="evidence",
            task_id="e1",
        )
        ready = make_task(
            "task-assess-research-readiness",
            depends_on=[extract.definition_id],
            status=readiness,
            executor_id="research_quality",
            task_id="r1",
        )
        analyze_task = make_task(
            "task-analyze",
            depends_on=[ready.definition_id],
            status=analyze,
            executor_id="analysis",
            task_id="a1",
        )
        write_task = make_task(
            "task-write-report",
            depends_on=[analyze_task.definition_id],
            status=write,
            executor_id="report",
            task_id="w1",
        )
        review_task = make_task(
            "task-review-report",
            depends_on=[write_task.definition_id],
            status=review,
            executor_id="review",
            task_id="v1",
        )
        return collect, extract, ready, analyze_task, write_task, review_task

    def test_case_01_submit_returns_stable_research_id(self) -> None:
        response = self.client.post("/research", json={"brief": BRIEF})
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertTrue(payload["research_id"])
        self.assertEqual(payload["research_id"], payload["run_id"])
        self.assertTrue(payload["project_id"])
        self.assertIn(payload["execution_status"], {"QUEUED", "RUNNING"})
        self.assertIsNone(payload["product_outcome"])
        self.assertFalse(payload["result_available"])
        self.assertEqual(
            response.headers.get("location"),
            f"/research/{payload['research_id']}",
        )

    def test_case_02_submit_uses_existing_execution_path(self) -> None:
        with patch.object(
            self.container.agency,
            "start_research",
            wraps=self.container.agency.start_research,
        ) as mocked:
            response = self.client.post("/research", json={"brief": BRIEF})
            self.assertEqual(response.status_code, 202)
            mocked.assert_called()
        self.container._test_llm_client.generate.assert_called()

    def test_case_13_active_result_conflict(self) -> None:
        research_id = self.client.post("/research", json={"brief": BRIEF}).json()[
            "research_id"
        ]
        response = self.client.get(f"/research/{research_id}/result")
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error"]["code"], "research_not_terminal")
        self.assertNotIn("Traceback", str(body))
        self.assertNotIn("openai", str(body).lower())

    def test_case_14_unknown_research_404(self) -> None:
        response = self.client.get("/research/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "research_not_found")
        result = self.client.get("/research/does-not-exist/result")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json()["error"]["code"], "research_not_found")

    def test_get_status_after_submit(self) -> None:
        research_id = self.client.post("/research", json={"brief": BRIEF}).json()[
            "research_id"
        ]
        status_payload = self.client.get(f"/research/{research_id}").json()
        self.assertEqual(status_payload["research_id"], research_id)
        self.assertIn("phase", status_payload)
        self.assertNotIn("tasks", status_payload)

    def test_case_09_approved_terminal(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Approved Fixture"},
        ).json()["id"]
        run_id = "approved-facade-run"

        def seed(project_id: str, run_id: str) -> None:
            sources = self.container.source_service._source_repository
            evidence = self.container.evidence_service._evidence_repository
            findings = self.container.finding_service._finding_repository
            reports = self.container.report_query_service._report_repository
            reviews = self.container.review_query_service._review_repository
            artifacts = self.container.artifact_service._artifact_repository
            sources.create(
                Source(
                    id="src-1",
                    project_id=project_id,
                    url="https://example.com/a",
                    canonical_url="https://example.com/a",
                    title="A",
                    retrieved_at="2026-08-12T00:00:00+00:00",
                    workflow_run_refs=(run_id,),
                    retrieval_status=RetrievalStatus.ACQUIRED,
                    content_text="SECRET",
                ),
            )
            evidence.create(
                Evidence(
                    id="ev-1",
                    project_id=project_id,
                    source_id="src-1",
                    source_content_checksum="x",
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    statement="Evidence statement",
                    source_excerpt="excerpt",
                    created_at="2026-08-12T00:00:00+00:00",
                    evidence_type=EvidenceType.DIRECT_EXCERPT,
                    deduplication_key="ev-1",
                ),
            )
            findings.create(
                Finding(
                    id="f-1",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    statement="Finding statement",
                    rationale="r",
                    evidence_refs=("ev-1",),
                    created_at="2026-08-12T00:00:00+00:00",
                    finding_type=FindingType.SYNTHESIS,
                    deduplication_key="f-1",
                ),
            )
            reports.create(
                Report(
                    id="rep-1",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    title="Report",
                    language="en",
                    sections=(),
                    executive_summary="Summary",
                    limitations=(),
                    created_at="2026-08-12T00:00:00+00:00",
                    generation_method="test",
                    finding_refs=("f-1",),
                    insight_refs=(),
                    evidence_refs=("ev-1",),
                    citation_registry={"c1": {"source_id": "src-1"}},
                    deduplication_key="rep-1",
                ),
            )
            artifacts.create(
                ArtifactRecord(
                    id="art-1",
                    project_id=project_id,
                    artifact_type="report",
                    title="A",
                    content="body",
                    run_id=run_id,
                    status="approved",
                    deduplication_key="art-1",
                    report_id="rep-1",
                ),
            )
            reviews.create(
                ReviewResult(
                    id="rev-1",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    report_id="rep-1",
                    review_attempt=1,
                    verdict=ReviewVerdict.APPROVE,
                    quality_dimensions=(),
                    issues=(),
                    summary="ok",
                    review_method="test",
                    created_at="2026-08-12T00:00:00+00:00",
                    deduplication_key="rev-1",
                    artifact_id="art-1",
                ),
            )

        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="complete",
            readiness={
                "ready_for_analysis": True,
                "research_outcome": "ready_for_analysis",
                "termination_reason": "",
                "blocking_information_need_ids": [],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(),
            seed_entities=seed,
        )
        status_payload = self.client.get(f"/research/{run_id}").json()
        self.assertEqual(status_payload["execution_status"], "TERMINAL")
        self.assertEqual(status_payload["phase"], "COMPLETED")
        self.assertEqual(status_payload["product_outcome"], "APPROVED")
        self.assertTrue(status_payload["result_available"])

        result = self.client.get(f"/research/{run_id}/result")
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body["outcome"], ResearchRunOutcome.APPROVED.value)
        self.assertEqual(body["research_id"], run_id)
        self.assertIn("provenance_summary", body)
        self.assertTrue(body["provenance_summary"]["links"])
        self.assertIn("budget_usage", body)
        self.assertNotIn("SECRET", str(body))

    def test_case_10_not_ready_terminal(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Not Ready Fixture"},
        ).json()["id"]
        run_id = "not-ready-facade-run"

        def seed(project_id: str, run_id: str) -> None:
            self.container.source_service._source_repository.create(
                Source(
                    id="src-nr",
                    project_id=project_id,
                    url="https://example.com/nr",
                    canonical_url="https://example.com/nr",
                    title="NR",
                    retrieved_at="2026-08-12T00:00:00+00:00",
                    workflow_run_refs=(run_id,),
                    retrieval_status=RetrievalStatus.ACQUIRED,
                    content_text="body",
                ),
            )
            self.container.evidence_service._evidence_repository.create(
                Evidence(
                    id="ev-nr",
                    project_id=project_id,
                    source_id="src-nr",
                    source_content_checksum="x",
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    statement="Evidence remains",
                    source_excerpt="ex",
                    created_at="2026-08-12T00:00:00+00:00",
                    evidence_type=EvidenceType.DIRECT_EXCERPT,
                    deduplication_key="ev-nr",
                ),
            )

        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="complete",
            readiness={
                "ready_for_analysis": False,
                "research_outcome": "insufficient_research",
                "termination_reason": "downstream_reserve_exhausted",
                "blocking_information_need_ids": ["IN1"],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(
                analyze=TaskStatus.SKIPPED,
                write=TaskStatus.SKIPPED,
                review=TaskStatus.SKIPPED,
            ),
            seed_entities=seed,
        )
        result = self.client.get(f"/research/{run_id}/result")
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body["outcome"], "NOT_READY")
        self.assertEqual(body["termination_reason"], "downstream_reserve_exhausted")
        self.assertGreaterEqual(body["evidence_summary"]["count"], 1)
        self.assertIsNone(body["latest_report"])

    def test_case_11_and_16_quality_rejected(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Quality Rejected Fixture"},
        ).json()["id"]
        run_id = "quality-rejected-facade-run"

        def seed(project_id: str, run_id: str) -> None:
            reports = self.container.report_query_service._report_repository
            reviews = self.container.review_query_service._review_repository
            artifacts = self.container.artifact_service._artifact_repository
            reports.create(
                Report(
                    id="rep-q",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    title="Rejected report",
                    language="en",
                    sections=(),
                    executive_summary="Summary",
                    limitations=("citation gaps",),
                    created_at="2026-08-12T00:00:00+00:00",
                    generation_method="test",
                    finding_refs=(),
                    insight_refs=(),
                    evidence_refs=(),
                    citation_registry={},
                    deduplication_key="rep-q",
                    revision_number=2,
                ),
            )
            artifacts.create(
                ArtifactRecord(
                    id="art-q",
                    project_id=project_id,
                    artifact_type="report",
                    title="A",
                    content="body",
                    run_id=run_id,
                    status="rejected",
                    deduplication_key="art-q",
                    report_id="rep-q",
                ),
            )
            reviews.create(
                ReviewResult(
                    id="rev-q",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    report_id="rep-q",
                    review_attempt=2,
                    verdict=ReviewVerdict.REVISE,
                    quality_dimensions=(),
                    issues=(
                        ReviewIssue(
                            id="iss-1",
                            issue_type=ReviewIssueType.MISSING_CITATION,
                            severity=ReviewIssueSeverity.MAJOR,
                            message="missing citation",
                        ),
                    ),
                    summary="revise again",
                    review_method="test",
                    created_at="2026-08-12T00:00:00+00:00",
                    deduplication_key="rev-q",
                    artifact_id="art-q",
                ),
            )

        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="fail",
            readiness={
                "ready_for_analysis": True,
                "research_outcome": "ready_for_analysis",
                "termination_reason": "",
                "blocking_information_need_ids": [],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(review=TaskStatus.FAILED),
            seed_entities=seed,
        )
        body = self.client.get(f"/research/{run_id}/result").json()
        self.assertEqual(body["outcome"], "QUALITY_REJECTED")
        self.assertEqual(body["workflow_status"], WorkflowStatus.FAILED.value)
        self.assertIsNotNone(body["latest_report"])
        self.assertEqual(body["latest_review"]["verdict"], "revise")

    def test_case_12_execution_failed(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Execution Failed Fixture"},
        ).json()["id"]
        run_id = "execution-failed-facade-run"
        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="fail",
            readiness={
                "ready_for_analysis": False,
                "research_outcome": "insufficient_research",
                "termination_reason": "",
                "blocking_information_need_ids": [],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(
                readiness=TaskStatus.FAILED,
                analyze=TaskStatus.SKIPPED,
                write=TaskStatus.SKIPPED,
                review=TaskStatus.SKIPPED,
            ),
        )
        response = self.client.get(f"/research/{run_id}/result")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "EXECUTION_FAILED")

    def test_case_15_completed_alone_not_approved(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Completed Not Approved"},
        ).json()["id"]
        run_id = "completed-not-approved"
        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="complete",
            readiness={
                "ready_for_analysis": False,
                "research_outcome": "insufficient_research",
                "termination_reason": "sufficiency_budget_exhausted",
                "blocking_information_need_ids": ["IN1"],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(
                analyze=TaskStatus.SKIPPED,
                write=TaskStatus.SKIPPED,
                review=TaskStatus.SKIPPED,
            ),
        )
        body = self.client.get(f"/research/{run_id}/result").json()
        self.assertEqual(body["workflow_status"], "completed")
        self.assertEqual(body["outcome"], "NOT_READY")
        self.assertNotEqual(body["outcome"], "APPROVED")

    def test_case_18_result_delegates_to_p1_18_1_service(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Delegate"},
        ).json()["id"]
        run_id = "delegate-run"
        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="fail",
            readiness={
                "ready_for_analysis": False,
                "research_outcome": "insufficient_research",
                "termination_reason": "",
                "blocking_information_need_ids": [],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(
                readiness=TaskStatus.FAILED,
                analyze=TaskStatus.SKIPPED,
                write=TaskStatus.SKIPPED,
                review=TaskStatus.SKIPPED,
            ),
        )
        with patch.object(
            self.container.research_run_result_query_service,
            "get_for_run",
            wraps=self.container.research_run_result_query_service.get_for_run,
        ) as mocked:
            response = self.client.get(f"/research/{run_id}/result")
            self.assertEqual(response.status_code, 200)
            mocked.assert_called_with(run_id)

    def test_case_27_result_survives_service_recreation(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Durable"},
        ).json()["id"]
        run_id = "durable-run"
        self._seed_terminal_run(
            run_id=run_id,
            project_id=project_id,
            terminal="complete",
            readiness={
                "ready_for_analysis": False,
                "research_outcome": "insufficient_research",
                "termination_reason": "downstream_reserve_exhausted",
                "blocking_information_need_ids": [],
                "blocking_research_question_ids": [],
                "targeted_research_required": False,
                "research_question_assessments": [],
            },
            tasks_factory=lambda: self._pipeline(
                analyze=TaskStatus.SKIPPED,
                write=TaskStatus.SKIPPED,
                review=TaskStatus.SKIPPED,
            ),
        )
        first = self.client.get(f"/research/{run_id}/result").json()
        # Recreate query service over same durable repos.
        from application.query.research_run_result_query_service import (
            ResearchRunResultQueryService,
        )

        recreated = ResearchRunResultQueryService(
            workflow_run_repository=self.container.workflow_service._workflow_run_repository,
            source_repository=self.container.source_service._source_repository,
            evidence_repository=self.container.evidence_service._evidence_repository,
            finding_repository=self.container.finding_service._finding_repository,
            insight_repository=self.container.insight_service._insight_repository,
            report_repository=self.container.report_query_service._report_repository,
            review_repository=self.container.review_query_service._review_repository,
            artifact_repository=self.container.artifact_service._artifact_repository,
        )
        second = recreated.get_for_run(run_id).to_dict()
        self.assertEqual(first["outcome"], second["outcome"])
        self.assertEqual(first["run_id"], second["run_id"])

    def test_case_28_authorization_required(self) -> None:
        response = self._raw_client.post("/research", json={"brief": BRIEF})
        self.assertEqual(response.status_code, 401)

    def test_case_29_openapi_includes_research_routes(self) -> None:
        schema = self.client.get("/openapi.json").json()
        paths = schema["paths"]
        self.assertIn("/research", paths)
        self.assertIn("/research/{research_id}", paths)
        self.assertIn("/research/{research_id}/result", paths)
        self.assertEqual(paths["/research"]["post"]["operationId"], "submitResearch")

    def test_optional_project_id_reuses_project(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Existing"},
        ).json()["id"]
        response = self.client.post(
            "/research",
            json={"brief": BRIEF, "project_id": project_id},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["project_id"], project_id)

    def test_drain_pipeline_status_becomes_terminal(self) -> None:
        research_id = self.client.post("/research", json={"brief": BRIEF}).json()[
            "research_id"
        ]
        drain_background_runs(self.container)
        status_payload = self.client.get(f"/research/{research_id}").json()
        self.assertEqual(status_payload["execution_status"], "TERMINAL")
        self.assertEqual(status_payload["phase"], "COMPLETED")
        result = self.client.get(f"/research/{research_id}/result")
        # Deterministic embedded workers may complete without an approved
        # deliverable; product outcome must still be a safe non-5xx response.
        self.assertIn(result.status_code, {200, 409})
        if result.status_code == 200:
            self.assertIn(
                result.json()["outcome"],
                {"APPROVED", "NOT_READY", "QUALITY_REJECTED", "EXECUTION_FAILED"},
            )
        else:
            self.assertEqual(
                result.json()["error"]["code"],
                "research_result_unavailable",
            )


if __name__ == "__main__":
    unittest.main()
