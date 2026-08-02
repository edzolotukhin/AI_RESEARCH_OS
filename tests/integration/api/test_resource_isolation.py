from __future__ import annotations

import unittest
from uuid import uuid4
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from domain.ai.llm_response import LLMResponse

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import AuthenticatedTestClient, close_test_client, open_test_client
from tests.fixtures.planner_responses import VALID_PLANNER_JSON
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
)

BRIEF = {
    "client": "Purina",
    "project_title": "Isolation Project",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


class ResourceIsolationIntegrationTests(PostgreSQLIntegrationTestCase):

    def _build_two_clients(self):
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

        container_a = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container_a, name="principal-a")
        headers_a = auth_headers(container_a._test_api_key_plaintext)
        raw_a, _, context_a = open_test_client(container_a)

        container_b = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container_b, name="principal-b")
        headers_b = auth_headers(container_b._test_api_key_plaintext)
        raw_b, _, context_b = open_test_client(container_b)

        self.addCleanup(lambda: close_test_client(context_a, container_a))
        self.addCleanup(lambda: close_test_client(context_b, container_b))
        self.addCleanup(container_a.shutdown)
        self.addCleanup(container_b.shutdown)

        return (
            AuthenticatedTestClient(raw_a, headers_a),
            AuthenticatedTestClient(raw_b, headers_b),
            container_a,
        )

    def _create_owned_run(self, client_a):
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        run_id = client_a.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]
        return project_id, run_id

    def test_authorization_matrix_returns_404_for_foreign_principal(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)

        cases = [
            ("GET", f"/projects/{project_id}"),
            ("POST", f"/projects/{project_id}/research"),
            ("GET", f"/projects/{project_id}/workflow-runs"),
            ("GET", f"/projects/{project_id}/artifacts"),
            ("GET", f"/workflow-runs/{run_id}"),
            ("POST", f"/workflow-runs/{run_id}/resume"),
            ("GET", f"/workflow-runs/{run_id}/results"),
            ("GET", f"/workflow-runs/{run_id}/logs"),
            ("GET", f"/workflow-runs/{run_id}/artifacts"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                if method == "GET":
                    response = client_b.get(path)
                else:
                    body = {"brief": BRIEF} if "research" in path else None
                    response = client_b.post(path, json=body)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["error"]["code"], "entity_not_found")

    def test_project_list_excludes_foreign_projects(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        self._create_owned_run(client_a)
        self.assertEqual(client_b.get("/projects").json()["items"], [])

    def test_guessed_and_missing_uuid_responses_are_indistinguishable(self) -> None:
        _, client_b, _ = self._build_two_clients()
        guessed = client_b.get(f"/projects/{uuid4()}").json()
        missing = client_b.get(f"/projects/{uuid4()}").json()
        self.assertEqual(guessed["error"]["code"], missing["error"]["code"])
        self.assertEqual(guessed["error"]["code"], "entity_not_found")

    def test_principal_b_cannot_access_principal_a_project(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        self.assertEqual(client_b.get(f"/projects/{project_id}").status_code, 404)

    def test_principal_b_cannot_submit_research_to_foreign_project(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id = client_a.post("/projects", json={"name": "Project A"}).json()["id"]
        response = client_b.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        )
        self.assertEqual(response.status_code, 404)

    def test_principal_b_cannot_read_foreign_run(self) -> None:
        client_a, client_b, container_a = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)
        self.assertEqual(client_b.get(f"/workflow-runs/{run_id}").status_code, 404)
        runs = container_a.workflow_service.list_workflow_runs_for_project(project_id)
        self.assertEqual(len(runs), 1)

    def _seed_analysis_records(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> tuple[str, str]:
        from datetime import datetime, timezone
        from uuid import uuid4

        from domain.findings.finding import Finding
        from domain.findings.finding_type import FindingType
        from domain.findings.insight import Insight
        from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
            PostgreSQLFindingRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
            PostgreSQLInsightRepository,
        )

        finding_repo = PostgreSQLFindingRepository(self.session_factory)
        insight_repo = PostgreSQLInsightRepository(self.session_factory)
        now = datetime.now(timezone.utc).isoformat()
        finding_id = str(uuid4())
        insight_id = str(uuid4())
        finding_repo.create(
            Finding(
                id=finding_id,
                project_id=project_id,
                workflow_run_id=run_id,
                research_design_id="design-1",
                statement="Isolation finding",
                rationale="Rationale",
                evidence_refs=("evidence-1",),
                finding_type=FindingType.SYNTHESIS,
                analysis_method="deterministic",
                deduplication_key=f"dedup-{finding_id}",
                created_at=now,
            ),
        )
        insight_repo.create(
            Insight(
                id=insight_id,
                project_id=project_id,
                workflow_run_id=run_id,
                research_design_id="design-1",
                statement="Isolation insight",
                implication="Implication",
                finding_refs=(finding_id,),
                deduplication_key=f"dedup-{insight_id}",
                created_at=now,
            ),
        )
        return finding_id, insight_id

    def test_principal_b_cannot_access_foreign_findings_or_insights(self) -> None:
        client_a, client_b, _ = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)
        finding_id, insight_id = self._seed_analysis_records(
            project_id=project_id,
            run_id=run_id,
        )

        cases = [
            ("GET", f"/projects/{project_id}/findings"),
            ("GET", f"/findings/{finding_id}"),
            ("GET", f"/projects/{project_id}/insights"),
            ("GET", f"/insights/{insight_id}"),
            ("GET", f"/workflow-runs/{run_id}"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                response = client_b.get(path)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["error"]["code"], "entity_not_found")

    def _seed_report_records(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> tuple[str, str]:
        from datetime import datetime, timezone
        from uuid import uuid4

        from application.persistence.records import ArtifactRecord
        from application.report.deduplication import (
            DR06_RESEARCH_REPORT_TYPE,
            compute_artifact_deduplication_key,
            compute_content_checksum,
            compute_report_deduplication_key,
        )
        from domain.reports.report import Report
        from domain.reports.report_section import ReportSection
        from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
            PostgreSQLArtifactRepository,
        )
        from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
            PostgreSQLReportRepository,
        )

        now = datetime.now(timezone.utc).isoformat()
        report_id = str(uuid4())
        artifact_id = str(uuid4())
        content = "# Isolation Report\n\nBody."
        report_dedup = compute_report_deduplication_key(
            workflow_run_id=run_id,
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method="deterministic",
        )
        artifact_dedup = compute_artifact_deduplication_key(
            workflow_run_id=run_id,
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        PostgreSQLReportRepository(self.session_factory).create(
            Report(
                id=report_id,
                project_id=project_id,
                workflow_run_id=run_id,
                research_design_id="design-1",
                title="Isolation Report",
                language="en",
                sections=(
                    ReportSection(
                        id=str(uuid4()),
                        title="Section",
                        content="Grounded content.",
                        finding_refs=("finding-1",),
                        insight_refs=("insight-1",),
                        evidence_refs=("evidence-1",),
                        citation_ids=("S1",),
                    ),
                ),
                executive_summary="Summary",
                limitations=(),
                created_at=now,
                generation_method="deterministic",
                finding_refs=("finding-1",),
                insight_refs=("insight-1",),
                evidence_refs=("evidence-1",),
                citation_registry={
                    "S1": {
                        "citation_id": "S1",
                        "source_id": "source-1",
                        "title": "Source",
                        "canonical_url": "https://example.com",
                        "published_at": None,
                        "retrieved_at": now,
                        "source_type": "web",
                    },
                },
                deduplication_key=report_dedup,
            ),
        )
        PostgreSQLArtifactRepository(self.session_factory).create(
            ArtifactRecord(
                id=artifact_id,
                project_id=project_id,
                artifact_type=DR06_RESEARCH_REPORT_TYPE,
                title="Isolation Report",
                content=content,
                run_id=run_id,
                status="Generated",
                media_type="text/markdown",
                filename="isolation-report.md",
                content_checksum=compute_content_checksum(content),
                deduplication_key=artifact_dedup,
                report_id=report_id,
            ),
        )
        return report_id, artifact_id

    def test_principal_b_cannot_access_foreign_reports_or_artifacts(self) -> None:
        client_a, client_b, container_a = self._build_two_clients()
        project_id, run_id = self._create_owned_run(client_a)
        report_id, artifact_id = self._seed_report_records(
            project_id=project_id,
            run_id=run_id,
        )

        cases = [
            ("GET", f"/projects/{project_id}/reports"),
            ("GET", f"/reports/{report_id}"),
            ("GET", f"/artifacts/{artifact_id}"),
            ("GET", f"/artifacts/{artifact_id}/content"),
            ("GET", f"/workflow-runs/{run_id}"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                response = client_b.get(path)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["error"]["code"], "entity_not_found")

        run_summary = container_a.workflow_service.get_workflow_run(run_id)
        self.assertIsNotNone(run_summary)
        foreign_run = client_b.get(f"/workflow-runs/{run_id}")
        self.assertEqual(foreign_run.status_code, 404)
        self.assertNotIn("report_count", foreign_run.json().get("error", {}))


if __name__ == "__main__":
    unittest.main()
