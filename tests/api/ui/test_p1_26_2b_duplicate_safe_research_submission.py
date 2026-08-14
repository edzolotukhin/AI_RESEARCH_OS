from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import Response

from api.ui.research_facade import ResearchUiFacade
from application.persistence.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    IdempotencyConflictError,
)
from application.persistence.records import ResearchSubmissionStatus
from application.query.research_status import (
    ResearchExecutionStatus,
    ResearchPhase,
    ResearchStatusProjection,
)
from application.runtime.logical_submission_identity import (
    normalize_submission_key,
    project_id_for_submission,
)
from application.security.principal import AuthenticatedPrincipal
from application.services.research_submission_service import ResearchSubmissionService
from domain.project import Project
from domain.workflow_run import WorkflowRun
from infrastructure.persistence.memory.in_memory_research_submission_repository import (
    InMemoryResearchSubmissionRepository,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST
from tests.api.helpers import ApiTestCase

ROOT = Path(__file__).resolve().parents[3]


class _Agency:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.runs: dict[str, WorkflowRun] = {}
        self._lock = threading.Lock()
        self.planner_calls = 0
        self.workflow_creations = 0
        self.provider_calls = 0
        self.llm_calls = 0
        self.entered_planner = threading.Event()
        self.release_planner = threading.Event()
        self.release_planner.set()
        self.fail_planner = False

    def create_project(self, name, *, owner_principal_id=None, project_id=None):
        project = Project(id=project_id or str(uuid4()), name=name)
        project.owner_principal_id = owner_principal_id
        with self._lock:
            if project.id in self.projects:
                raise DuplicateEntityError("duplicate project")
            self.projects[project.id] = project
        return project

    def start_research(self, project, *, run_id=None):
        with self._lock:
            self.planner_calls += 1
        self.entered_planner.set()
        self.release_planner.wait(timeout=2)
        if self.fail_planner:
            raise RuntimeError("planner failed")
        run = WorkflowRun(id=run_id or str(uuid4()), project_id=project.id)
        with self._lock:
            self.workflow_creations += 1
            self.runs[run.id] = run
        return SimpleNamespace(workflow_run=run)


class _Authorization:
    def __init__(self, agency: _Agency, principal: AuthenticatedPrincipal) -> None:
        self.agency = agency
        self.principal = principal

    def require_project(self, principal, project_id):
        project = self.agency.projects.get(project_id)
        if project is None:
            raise EntityNotFoundError("missing project")
        if project.owner_principal_id != principal.principal_id:
            raise EntityNotFoundError("missing project")
        return project

    def require_run(self, principal, run_id):
        run = self.agency.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError("missing run")
        return run, self.require_project(principal, run.project_id)


class _Status:
    def __init__(self, agency: _Agency) -> None:
        self.agency = agency

    def get_status(self, run_id):
        run = self.agency.runs[run_id]
        return ResearchStatusProjection(
            research_id=run.id,
            project_id=run.project_id,
            execution_status=ResearchExecutionStatus.QUEUED,
            phase=ResearchPhase.QUEUED,
            product_outcome=None,
            result_available=False,
            workflow_status="created",
        )


class _WorkflowService:
    def __init__(self, agency: _Agency) -> None:
        self.agency = agency

    def get_workflow_run(self, run_id):
        run = self.agency.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError("missing run")
        return run


class PropertyADTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = AuthenticatedPrincipal("principal-a", "UI")
        self.agency = _Agency()
        self.repository = InMemoryResearchSubmissionRepository()
        self.service = ResearchSubmissionService(submission_repository=self.repository)
        self.container = SimpleNamespace(
            background_execution=None,
            agency=self.agency,
            workflow_service=_WorkflowService(self.agency),
            research_submission_service=self.service,
            research_status_query_service=_Status(self.agency),
        )
        self.authorization = _Authorization(self.agency, self.principal)
        self.facade = ResearchUiFacade(
            container=self.container,
            principal=self.principal,
            authorization=self.authorization,
        )
        self.key = str(uuid4())

    def submit(self, key=None, brief=None):
        return self.facade.submit_research(
            brief_payload=brief or dict(CANONICAL_BRIEF_REQUEST),
            response=Response(),
            submission_key=key or self.key,
        )

    def test_case_01_normal_submit_is_one_durable_submission(self):
        result = self.submit()
        self.assertEqual(1, len(self.repository._by_key))
        self.assertEqual(result["submission_status"], "completed")

    def test_case_02_normal_submit_returns_research_identity(self):
        result = self.submit()
        self.assertEqual(result["research_id"], result["run_id"])
        self.assertIn(result["research_id"], self.agency.runs)

    def test_case_03_double_submit_same_key_is_one_project(self):
        first, second = self.submit(), self.submit()
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(1, len(self.agency.projects))

    def test_case_04_sequential_duplicate_is_one_planner_and_run(self):
        first, second = self.submit(), self.submit()
        self.assertEqual(first["research_id"], second["research_id"])
        self.assertEqual((1, 1), (self.agency.planner_calls, self.agency.workflow_creations))

    def test_case_05_concurrent_duplicate_elects_one_winner(self):
        self.agency.release_planner.clear()
        results, errors = [], []
        def invoke():
            try:
                results.append(self.submit())
            except Exception as exc:  # pragma: no cover - assertion captures
                errors.append(exc)
        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke)
        first.start()
        self.assertTrue(self.agency.entered_planner.wait(1))
        second.start()
        second.join(1)
        self.agency.release_planner.set()
        first.join(1)
        self.assertFalse(errors)
        self.assertEqual((1, 1, 1), (len(self.agency.projects), self.agency.planner_calls, self.agency.workflow_creations))
        self.assertTrue(any(item["execution_status"] == "SUBMITTING" for item in results))

    def test_case_06_same_brief_new_key_is_intentional_new_research(self):
        self.submit()
        self.submit(str(uuid4()))
        self.assertEqual((2, 2, 2), (len(self.agency.projects), self.agency.planner_calls, len(self.agency.runs)))

    def test_case_07_timeout_reconciliation_is_read_only(self):
        self.submit()
        before = (len(self.agency.projects), self.agency.planner_calls, len(self.agency.runs))
        status = self.facade.get_submission_status(self.key)
        self.assertEqual(before, (len(self.agency.projects), self.agency.planner_calls, len(self.agency.runs)))
        self.assertTrue(status["research_url"])

    def test_case_08_replay_during_planning_does_not_duplicate(self):
        self.agency.release_planner.clear()
        thread = threading.Thread(target=self.submit)
        thread.start()
        self.assertTrue(self.agency.entered_planner.wait(1))
        replay = self.submit()
        self.assertEqual("SUBMITTING", replay["execution_status"])
        self.assertEqual(1, self.agency.planner_calls)
        self.agency.release_planner.set()
        thread.join(1)

    def test_case_09_submission_without_run_is_readable(self):
        project_id = project_id_for_submission(principal_id=self.principal.principal_id, submission_key=self.key)
        self.agency.create_project("x", owner_principal_id=self.principal.principal_id, project_id=project_id)
        self.service.resolve_submission(project_id=project_id, idempotency_key=self.key, request_fingerprint="fp", correlation_id=None, source="ui")
        status = self.facade.get_submission_status(self.key)
        self.assertEqual("SUBMITTING", status["execution_status"])
        self.assertEqual(status["research_id"], status["run_id"])

    def test_case_10_project_without_submission_is_not_false_success(self):
        project_id = project_id_for_submission(principal_id=self.principal.principal_id, submission_key=self.key)
        self.agency.create_project("x", owner_principal_id=self.principal.principal_id, project_id=project_id)
        with self.assertRaises(EntityNotFoundError):
            self.facade.get_submission_status(self.key)

    def test_case_11_run_is_exposed_when_visible(self):
        result = self.submit()
        status = self.facade.get_submission_status(self.key)
        self.assertEqual(result["research_id"], status["research_id"])

    def test_case_12_terminal_or_visible_replay_resolves_same_run(self):
        first = self.submit()
        self.assertEqual(first["run_id"], self.submit()["run_id"])

    def test_case_13_unknown_key_creates_no_work(self):
        with self.assertRaises(EntityNotFoundError):
            self.facade.get_submission_status(str(uuid4()))
        self.assertEqual(0, self.agency.planner_calls)

    def test_case_14_malformed_key_fails_closed(self):
        with self.assertRaises(ValueError):
            self.submit("not-a-key")
        self.assertEqual(0, len(self.agency.projects))

    def test_case_15_planner_failure_preserves_failed_claim(self):
        self.agency.fail_planner = True
        with self.assertRaises(RuntimeError):
            self.submit()
        replay = self.submit()
        self.assertEqual("failed", replay["submission_status"])
        self.assertEqual(1, self.agency.planner_calls)

    def test_case_16_failed_replay_never_reenters_planner(self):
        self.agency.fail_planner = True
        with self.assertRaises(RuntimeError): self.submit()
        self.submit()
        self.assertEqual((1, 0), (self.agency.planner_calls, self.agency.workflow_creations))

    def test_case_17_repository_reload_preserves_idempotency(self):
        first = self.submit()
        self.container.research_submission_service = ResearchSubmissionService(submission_repository=self.repository)
        second = self.submit()
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(1, self.agency.planner_calls)

    def test_case_18_ui_contains_button_guard_and_no_auto_submit_retry(self):
        js = (ROOT / "api/static/research.js").read_text()
        self.assertIn("button.disabled = true", js)
        self.assertNotIn("form.submit()", js)

    def test_case_19_form_contains_opaque_submission_key_not_credentials(self):
        html = (ROOT / "api/templates/research/new.html").read_text()
        self.assertIn('name="submission_key"', html)
        self.assertNotIn("UI_INTERNAL_API_KEY", html)
        self.assertNotIn("Bearer", html)

    def test_case_20_reconciliation_deep_link_is_durable(self):
        self.submit()
        self.assertRegex(self.facade.get_submission_status(self.key)["research_url"], r"^/ui/research/[0-9a-f-]+$")

    def test_case_21_project_identity_is_owner_scoped(self):
        other = project_id_for_submission(principal_id="principal-b", submission_key=self.key)
        ours = project_id_for_submission(principal_id="principal-a", submission_key=self.key)
        self.assertNotEqual(ours, other)

    def test_case_22_key_is_opaque_uuid4_and_canonical(self):
        self.assertEqual(self.key, normalize_submission_key(self.key.upper()))
        with self.assertRaises(ValueError): normalize_submission_key("00000000-0000-1000-8000-000000000000")

    def test_case_23_property_ac_files_are_not_imported(self):
        source = (ROOT / "api/ui/research_facade.py").read_text() + (ROOT / "application/runtime/logical_submission_identity.py").read_text()
        self.assertNotIn("retrieval_portfolio", source)
        self.assertNotIn("RetrievalArm", source)

    def test_case_24_no_provider_calls(self):
        self.submit(); self.submit()
        self.assertEqual(0, self.agency.provider_calls)

    def test_case_25_no_llm_calls_in_offline_boundary(self):
        self.submit(); self.submit()
        self.assertEqual(0, self.agency.llm_calls)

    def test_case_26_conflicting_brief_same_key_fails_closed(self):
        self.submit()
        changed = {**CANONICAL_BRIEF_REQUEST, "business_question": "Different"}
        with self.assertRaises(IdempotencyConflictError):
            self.submit(brief=changed)
        self.assertEqual(1, self.agency.planner_calls)


class PropertyADRouteTests(ApiTestCase):
    def test_case_27_new_form_issues_uuid_submission_key(self):
        response = self.client.get("/ui/research/new")
        self.assertEqual(200, response.status_code)
        self.assertRegex(
            response.text,
            r'name="submission_key" type="hidden" value="[0-9a-f-]{36}"',
        )

    def test_case_28_normal_post_redirects_to_research_identity(self):
        key = str(uuid4())
        facade = Mock()
        facade.submit_research.return_value = {"research_id": "run-1"}
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.client.post(
                "/ui/research",
                data={"business_question": "Question", "submission_key": key},
                follow_redirects=False,
            )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/ui/research/run-1", response.headers["location"])
        facade.submit_research.assert_called_once()

    def test_case_29_pending_replay_redirects_to_reconciliation(self):
        key = str(uuid4())
        facade = Mock()
        facade.submit_research.return_value = {"research_id": None}
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.client.post(
                "/ui/research",
                data={"business_question": "Question", "submission_key": key},
                follow_redirects=False,
            )
        self.assertEqual(303, response.status_code)
        self.assertEqual(
            f"/ui/research/submissions/{key}",
            response.headers["location"],
        )

    def test_case_30_reconciliation_get_is_read_only_and_redirects_when_visible(self):
        key = str(uuid4())
        facade = Mock()
        facade.get_submission_status.return_value = {
            "submission_status": "completed",
            "research_url": "/ui/research/run-1",
        }
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.client.get(
                f"/ui/research/submissions/{key}",
                follow_redirects=False,
            )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/ui/research/run-1", response.headers["location"])
        facade.get_submission_status.assert_called_once_with(key)


if __name__ == "__main__":
    unittest.main()
