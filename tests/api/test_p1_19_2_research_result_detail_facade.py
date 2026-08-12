"""P1-19.2 public Research result detail facade offline acceptance."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from application.persistence.records import ArtifactRecord
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
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
from tests.api.test_p1_19_1_research_facade import ResearchFacadeApiTests
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF


class ResearchResultDetailFacadeApiTests(ResearchFacadeApiTests):
    def _seed_approved_detail_fixture(self, *, run_id: str, project_id: str) -> None:
        def seed(project_id: str, run_id: str) -> None:
            self.container.source_service._source_repository.create(
                Source(
                    id="src-detail",
                    project_id=project_id,
                    url="https://example.com/detail",
                    canonical_url="https://example.com/detail",
                    title="Detail Source",
                    publisher="Detail Publisher",
                    retrieved_at="2026-08-12T00:00:00+00:00",
                    workflow_run_refs=(run_id,),
                    retrieval_status=RetrievalStatus.ACQUIRED,
                    content_text="SECRET_SOURCE_BODY",
                ),
            )
            self.container.evidence_service._evidence_repository.create(
                Evidence(
                    id="ev-detail",
                    project_id=project_id,
                    source_id="src-detail",
                    source_content_checksum="x",
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    statement="Evidence statement",
                    source_excerpt="Persisted excerpt",
                    created_at="2026-08-12T00:00:00+00:00",
                    evidence_type=EvidenceType.DIRECT_EXCERPT,
                    deduplication_key="ev-detail",
                ),
            )
            self.container.finding_service._finding_repository.create(
                Finding(
                    id="f-detail",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    statement="Finding statement",
                    rationale="Finding rationale",
                    evidence_refs=("ev-detail",),
                    created_at="2026-08-12T00:00:00+00:00",
                    finding_type=FindingType.SYNTHESIS,
                    deduplication_key="f-detail",
                ),
            )
            reports = self.container.report_query_service._report_repository
            reviews = self.container.review_query_service._review_repository
            artifacts = self.container.artifact_service._artifact_repository
            reports.create(
                Report(
                    id="rep-detail",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    title="Detail Report",
                    language="en",
                    sections=(
                        ReportSection(
                            id="sec-detail",
                            title="Section",
                            content="Report section content",
                            finding_refs=("f-detail",),
                            evidence_refs=("ev-detail",),
                        ),
                    ),
                    executive_summary="Detail executive summary",
                    limitations=("detail-limitation",),
                    created_at="2026-08-12T00:00:00+00:00",
                    generation_method="test",
                    finding_refs=("f-detail",),
                    insight_refs=(),
                    evidence_refs=("ev-detail",),
                    citation_registry={"c1": {"source_id": "src-detail"}},
                    deduplication_key="rep-detail",
                    revision_number=1,
                ),
            )
            artifacts.create(
                ArtifactRecord(
                    id="art-detail",
                    project_id=project_id,
                    artifact_type="report",
                    title="Artifact",
                    content="artifact",
                    run_id=run_id,
                    status="approved",
                    deduplication_key="art-detail",
                    report_id="rep-detail",
                ),
            )
            reviews.create(
                ReviewResult(
                    id="rev-detail",
                    project_id=project_id,
                    workflow_run_id=run_id,
                    research_design_id="d1",
                    report_id="rep-detail",
                    review_attempt=1,
                    verdict=ReviewVerdict.APPROVE,
                    quality_dimensions=(),
                    issues=(),
                    summary="Approved",
                    review_method="test",
                    created_at="2026-08-12T00:00:00+00:00",
                    deduplication_key="rev-detail",
                    artifact_id="art-detail",
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

    def test_case_01_detail_endpoint_returns_inspectable_payload(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Detail Approved"},
        ).json()["id"]
        run_id = "detail-facade-approved"
        self._seed_approved_detail_fixture(run_id=run_id, project_id=project_id)

        response = self.client.get(f"/research/{run_id}/result/detail")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["outcome"], "APPROVED")
        self.assertIn("detail", body)
        self.assertEqual(body["detail"]["sources"][0]["title"], "Detail Source")
        self.assertEqual(
            body["detail"]["evidence"][0]["source_excerpt"]["value"],
            "Persisted excerpt",
        )
        self.assertEqual(len(body["detail"]["report"]["sections"]), 1)
        self.assertTrue(body["provenance_summary"]["links"])

    def test_case_18_result_endpoint_unchanged(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Backcompat"},
        ).json()["id"]
        run_id = "detail-facade-backcompat"
        self._seed_approved_detail_fixture(run_id=run_id, project_id=project_id)

        summary = self.client.get(f"/research/{run_id}/result").json()
        detail = self.client.get(f"/research/{run_id}/result/detail").json()

        for key in summary:
            self.assertEqual(detail[key], summary[key])
        self.assertIn("detail", detail)
        self.assertNotIn("detail", summary)

    def test_case_19_bearer_auth_required(self) -> None:
        response = self._raw_client.get("/research/missing/result/detail")
        self.assertEqual(response.status_code, 401)

    def test_case_20_unknown_research_404(self) -> None:
        response = self.client.get("/research/unknown-detail-run/result/detail")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "research_not_found")

    def test_case_21_active_research_409(self) -> None:
        research_id = self.client.post("/research", json={"brief": BRIEF}).json()[
            "research_id"
        ]
        response = self.client.get(f"/research/{research_id}/result/detail")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "research_not_terminal")

    def test_case_14_no_source_content_text(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "No Source Body"},
        ).json()["id"]
        run_id = "detail-facade-no-body"
        self._seed_approved_detail_fixture(run_id=run_id, project_id=project_id)

        body = self.client.get(f"/research/{run_id}/result/detail").json()
        payload = json.dumps(body)
        self.assertNotIn("SECRET_SOURCE_BODY", payload)
        self.assertNotIn("content_text", payload)

    def test_case_15_no_raw_exceptions(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Execution Failed Detail"},
        ).json()["id"]
        run_id = "detail-facade-failed"
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
        body = self.client.get(f"/research/{run_id}/result/detail").json()
        payload = json.dumps(body)
        self.assertEqual(body["outcome"], "EXECUTION_FAILED")
        self.assertNotIn("Traceback", payload)

    def test_case_16_read_only_path(self) -> None:
        project_id = self.client.post(
            "/projects",
            json={"name": "Read Only Detail"},
        ).json()["id"]
        run_id = "detail-facade-read-only"
        self._seed_approved_detail_fixture(run_id=run_id, project_id=project_id)

        with patch.object(
            self.container.research_run_result_query_service,
            "get_detail_for_run",
            wraps=self.container.research_run_result_query_service.get_detail_for_run,
        ) as mocked:
            response = self.client.get(f"/research/{run_id}/result/detail")
            self.assertEqual(response.status_code, 200)
            mocked.assert_called_once_with(run_id)

    def test_openapi_includes_detail_route(self) -> None:
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/research/{research_id}/result/detail", schema["paths"])


if __name__ == "__main__":
    unittest.main()
