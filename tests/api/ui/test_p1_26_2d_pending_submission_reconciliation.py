from __future__ import annotations

import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from application.security.principal import AuthenticatedPrincipal
from domain.project import Project
from domain.workflow_run import WorkflowRun
from tests.api.helpers import ApiTestCase
from tests.api.ui import test_p1_26_2b_duplicate_safe_research_submission as ad


class PropertyADPendingTests(unittest.TestCase):
    """PROPERTY AD-P: a durable claim remains readable before run materialization."""

    def setUp(self) -> None:
        self.principal = AuthenticatedPrincipal("principal-a", "UI")
        self.agency = ad._Agency()
        self.repository = ad.InMemoryResearchSubmissionRepository()
        self.service = ad.ResearchSubmissionService(
            submission_repository=self.repository,
        )
        self.container = ad.SimpleNamespace(
            background_execution=None,
            agency=self.agency,
            workflow_service=ad._WorkflowService(self.agency),
            research_submission_service=self.service,
            research_status_query_service=ad._Status(self.agency),
        )
        self.authorization = ad._Authorization(self.agency, self.principal)
        self.facade = ad.ResearchUiFacade(
            container=self.container,
            principal=self.principal,
            authorization=self.authorization,
        )
        self.key = str(uuid4())

    def submit(self):
        return self.facade.submit_research(
            brief_payload=dict(ad.CANONICAL_BRIEF_REQUEST),
            response=ad.Response(),
            submission_key=self.key,
        )

    def test_p_case_01_known_pending_submission_returns_pending_projection(self):
        project_id, reservation = self._register_pending()
        status = self.facade.get_submission_status(self.key)
        self.assertEqual("SUBMITTING", status["execution_status"])
        self.assertEqual(project_id, status["project_id"])
        self.assertEqual(reservation.run_id, status["research_id"])
        self.assertEqual(reservation.run_id, status["run_id"])
        self.assertIsNone(status["research_url"])

    def test_p_case_02_pending_to_materialized_preserves_identity(self):
        _, reservation = self._register_pending()
        pending = self.facade.get_submission_status(self.key)
        self.agency.runs[reservation.run_id] = WorkflowRun(
            id=reservation.run_id,
            project_id=pending["project_id"],
        )
        materialized = self.facade.get_submission_status(self.key)
        self.assertEqual(pending["run_id"], materialized["run_id"])
        self.assertEqual(f"/ui/research/{reservation.run_id}", materialized["research_url"])

    def test_p_case_03_materialized_to_terminal_preserves_identity(self):
        agency = self.agency

        class _TerminalStatus:
            def get_status(self, run_id):
                run = agency.runs[run_id]
                return ad.ResearchStatusProjection(
                    research_id=run.id,
                    project_id=run.project_id,
                    execution_status=ad.ResearchExecutionStatus.TERMINAL,
                    phase=ad.ResearchPhase.COMPLETED,
                    product_outcome=None,
                    result_available=True,
                    workflow_status="completed",
                )

        self.container.research_status_query_service = _TerminalStatus()
        result = self.submit()
        first = self.facade.get_submission_status(self.key)
        second = self.facade.get_submission_status(self.key)
        self.assertEqual(result["run_id"], first["run_id"])
        self.assertEqual(first["run_id"], second["run_id"])

    def test_p_case_04_wrong_owner_receives_no_pending_metadata(self):
        self._register_pending()
        other = ad.ResearchUiFacade(
            container=self.container,
            principal=AuthenticatedPrincipal("principal-b", "Other"),
            authorization=self.authorization,
        )
        with self.assertRaises(EntityNotFoundError):
            other.get_submission_status(self.key)

    def test_p_case_05_missing_project_fails_closed(self):
        project_id, _ = self._register_pending()
        del self.agency.projects[project_id]
        with self.assertRaises(EntityNotFoundError):
            self.facade.get_submission_status(self.key)

    def test_p_case_06_corrupt_run_linkage_fails_closed(self):
        _, reservation = self._register_pending()
        other = Project(id=str(uuid4()), name="other")
        other.owner_principal_id = self.principal.principal_id
        self.agency.projects[other.id] = other
        self.agency.runs[reservation.run_id] = WorkflowRun(
            id=reservation.run_id,
            project_id=other.id,
        )
        with self.assertRaises(AccessDeniedError):
            self.facade.get_submission_status(self.key)

    def test_p_case_07_reconciliation_is_read_only(self):
        self._register_pending()
        before = (
            len(self.agency.projects),
            self.agency.planner_calls,
            self.agency.workflow_creations,
            self.agency.provider_calls,
            self.agency.llm_calls,
        )
        self.facade.get_submission_status(self.key)
        self.assertEqual(
            before,
            (
                len(self.agency.projects),
                self.agency.planner_calls,
                self.agency.workflow_creations,
                self.agency.provider_calls,
                self.agency.llm_calls,
            ),
        )

    def _register_pending(self):
        project_id = ad.project_id_for_submission(
            principal_id=self.principal.principal_id,
            submission_key=self.key,
        )
        self.agency.create_project(
            "pending",
            owner_principal_id=self.principal.principal_id,
            project_id=project_id,
        )
        reservation = self.service.resolve_submission(
            project_id=project_id,
            idempotency_key=self.key,
            request_fingerprint="fp",
            correlation_id=None,
            source="ui",
        )
        return project_id, reservation


class PropertyADPendingRouteTests(ApiTestCase):
    def test_p_case_08_pending_html_is_200_and_does_not_redirect(self):
        key = str(uuid4())
        facade = Mock()
        facade.get_submission_status.return_value = self._pending(key)
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.client.get(f"/ui/research/submissions/{key}")
        self.assertEqual(200, response.status_code)
        self.assertIn("Your submission is durable", response.text)
        facade.get_submission_status.assert_called_once_with(key)

    def test_p_case_09_pending_json_is_200(self):
        key = str(uuid4())
        facade = Mock()
        facade.get_submission_status.return_value = self._pending(key)
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.client.get(f"/ui/research/submissions/{key}/status.json")
        self.assertEqual(200, response.status_code)
        self.assertEqual("SUBMITTING", response.json()["execution_status"])
        self.assertEqual(key, response.json()["submission_key"])

    def test_p_case_10_unknown_key_remains_404(self):
        key = str(uuid4())
        facade = Mock()
        facade.get_submission_status.side_effect = EntityNotFoundError("missing")
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            html = self.client.get(f"/ui/research/submissions/{key}")
            json = self.client.get(f"/ui/research/submissions/{key}/status.json")
        self.assertEqual((404, 404), (html.status_code, json.status_code))

    @staticmethod
    def _pending(key):
        return {
            "submission_key": key,
            "submission_status": "pending",
            "project_id": "project-1",
            "research_id": "reserved-run-1",
            "run_id": "reserved-run-1",
            "execution_status": "SUBMITTING",
            "research_url": None,
        }


if __name__ == "__main__":
    unittest.main()
