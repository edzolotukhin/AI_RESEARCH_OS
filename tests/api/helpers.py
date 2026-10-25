from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from unittest.mock import Mock

from fastapi.testclient import TestClient

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.container import ApplicationContainer
from domain.ai.llm_response import LLMResponse
from domain.research_brief import ResearchBrief
from application.deliverables.presentation_jobs import PresentationJob

from api.app import create_fastapi_app

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from infrastructure.search.deterministic_search_adapter import DeterministicSourceRetriever
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor


def build_test_container(
    *,
    temp_dir: str | None = None,
    persistence_backend: str = "memory",
    background_execution_mode: str | None = None,
) -> ApplicationContainer:
    mock_llm = create_brief_aligned_llm_mock()

    if temp_dir is None:
        temp_dir = tempfile.mkdtemp()

    if background_execution_mode is None:
        if persistence_backend == "memory":
            background_execution_mode = "embedded"
        elif persistence_backend == "postgresql":
            background_execution_mode = "external"

    container = create_application_container(
        config=ApplicationConfig(
            projects_root=temp_dir,
            persistence_backend=persistence_backend,
            background_execution_mode=background_execution_mode,
            deterministic_stage_executors=True,
            search_provider="deterministic",
        ),
        overrides=ApplicationOverrides(llm_client=mock_llm),
    )
    container._test_llm_client = mock_llm  # test helper only
    if container.authentication_service is not None:
        bootstrap_test_api_key(container)
    return container


def open_test_client(
    container: ApplicationContainer | None = None,
) -> tuple[TestClient, ApplicationContainer, TestClient]:
    """Open a TestClient and enter its lifespan context."""
    app_container = container or build_test_container()
    app = create_fastapi_app(container=app_container)
    context = TestClient(app)
    client = context.__enter__()
    return client, app_container, context


def close_test_client(context: TestClient, container: ApplicationContainer) -> None:
    context.__exit__(None, None, None)
    container.shutdown()


def drain_background_runs(
    container: ApplicationContainer,
    *,
    worker_id: str = "test-worker",
    max_runs: int = 100,
) -> int:
    if container.worker_execution_service is None:
        return 0
    drained = container.worker_execution_service.drain_runnable_runs(
        worker_id,
        max_runs=max_runs,
    )
    deliverables = container.project_deliverables_service
    for _ in range(max_runs):
        if not deliverables.process_next_presentation(
            f"{worker_id}-presentation"
        ):
            break
    return drained


class _DeterministicPresentationJobs:
    """Provider-free presentation scheduling boundary for API workflow tests."""

    def __init__(self) -> None:
        self._jobs: dict[tuple[str, ...], PresentationJob] = {}

    @staticmethod
    def _key(values) -> tuple[str, ...]:
        return tuple(str(values[name]) for name in (
            "project_id", "method", "source_id", "source_version",
            "template_version", "renderer_version",
        ))

    def find(self, **kwargs):
        return self._jobs.get(self._key(kwargs))

    def schedule(self, **kwargs):
        key = self._key(kwargs)
        job = self._jobs.get(key)
        if job is None:
            now = datetime.now(timezone.utc)
            initial_state = kwargs.pop("initial_state", "pending")
            job = PresentationJob(
                id=str(uuid5(NAMESPACE_URL, "|".join(key))),
                state=initial_state,
                attempts=0,
                lease_until=None,
                claimed_by=None,
                created_at=now,
                updated_at=now,
                completed_deliverable_id=None,
                failure_code=None,
                **kwargs,
            )
            self._jobs[key] = job
        return job

    def _replace(self, job, **changes):
        updated = replace(job, **changes)
        self._jobs[self._key(vars(updated))] = updated
        return updated

    def retry(self, job_id):
        job = self._by_id(job_id)
        return self._replace(job, state="pptx_pending", failure_code=None)

    def claim_next(self, worker_id):
        job = next((item for item in self._jobs.values()
                    if item.state in {"pending", "pptx_pending", "retry_wait"}), None)
        if job is None:
            return None
        return self._replace(
            job,
            state="pptx_processing",
            attempts=job.attempts + 1,
            claimed_by=worker_id,
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=30),
        )

    def complete(self, job_id, worker_id, deliverable_id):
        job = self._by_id(job_id)
        self._replace(
            job,
            state="finalization_complete",
            claimed_by=None,
            lease_until=None,
            completed_deliverable_id=deliverable_id,
        )
        return True

    def fail(self, job_id, worker_id, failure_code):
        job = self._by_id(job_id)
        self._replace(
            job,
            state="failed_terminal",
            claimed_by=None,
            lease_until=None,
            failure_code=failure_code,
        )
        return True

    def transition(self, job_id, *, expected, state, failure_code=None):
        job = self._by_id(job_id)
        if job.state in expected:
            job = self._replace(job, state=state, failure_code=failure_code)
        return job

    def _by_id(self, job_id):
        return next(item for item in self._jobs.values() if item.id == job_id)


class _DeterministicPptxRenderer:
    version = "pptx-test-v1"
    template_version = "desk-test-v1"
    media_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

    @staticmethod
    def render(document):
        return b"PK\x03\x04" + document.source_id.encode("utf-8")


def configure_test_presentation_scheduling(container) -> None:
    """Attach the explicit provider-free scheduling boundary to a test container."""
    service = container.project_deliverables_service
    service.presentation_jobs = _DeterministicPresentationJobs()
    service.pptx_renderer = _DeterministicPptxRenderer()


def prepare_approved_desk_project(container, project_id: str, brief_payload: dict):
    """Prepare the canonical approved-design precondition for Desk API tests."""
    project = container.project_service.get_project(project_id)
    project.selected_methods = ("DESK",)
    container.project_service.save_project(project)
    brief = ResearchBrief.from_dict(brief_payload)
    container.project_planning_service.save_brief(project, brief)
    project = container.project_service.get_project(project_id)
    container.project_planning_service.generate_design(project)
    project = container.project_service.get_project(project_id)
    container.project_planning_service.approve_design(
        project,
        actor_id=project.owner_principal_id or "test-owner",
        expected_design_id=project.current_research_design.id,
    )
    return container.project_service.get_project(project_id)


def activate_approved_desk_project(container, project_id: str, brief_payload: dict):
    """Prepare and activate Desk through the canonical approved-design boundary."""
    project = prepare_approved_desk_project(container, project_id, brief_payload)
    return container.project_planning_service.activate_desk(project)


def submit_approved_desk_run(container, project_id: str, *, run_id: str):
    """Submit another run from the same approved, frozen Desk design."""
    project = container.project_service.get_project(project_id)
    container.project_planning_service._require_activation(project, "DESK")
    template = container.project_planning_service.workflow_mapper.from_research_design(
        project.current_research_design,
        project,
    )
    return container.agency.start_research_from_template(
        project,
        template,
        run_id=run_id,
    ).workflow_run


def dated_desk_overrides(llm_client):
    """Use deterministic material with an explicit observation period."""
    class DatedRetriever(DeterministicSourceRetriever):
        def retrieve(self, candidate):
            source = super().retrieve(candidate)
            if source.content_text:
                source = replace(
                    source,
                    content_text=source.content_text + " Pet food Germany brand awareness. Observation period: 2026.",
                )
            return source

    class DatedExtractor(DeterministicEvidenceExtractor):
        def extract(self, **kwargs):
            return [
                replace(
                    item,
                    statement=item.statement + " Pet food Germany.",
                    source_excerpt=item.source_excerpt + " Pet food Germany brand awareness. Observation period: 2026.",
                    metadata={**item.metadata, "observation_period": "2026"},
                )
                for item in super().extract(**kwargs)
            ]

    return ApplicationOverrides(
        llm_client=llm_client,
        source_retriever=DatedRetriever(),
        evidence_extractor=DatedExtractor(),
    )


def build_test_client(
    container: ApplicationContainer | None = None,
) -> tuple[TestClient, ApplicationContainer]:
    """One-shot helper for smoke tests; prefer ApiTestCase for suites."""
    client, app_container, context = open_test_client(container)
    client._pf05_context = context
    return client, app_container


class AuthenticatedTestClient:
    """Injects default Authorization headers for protected API tests."""

    def __init__(self, client: TestClient, auth_headers: dict[str, str]):
        self._client = client
        self._auth_headers = auth_headers

    def _merge_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self._auth_headers)
        if headers:
            merged.update(headers)
        return merged

    def get(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.post(url, **kwargs)

    def put(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.put(url, **kwargs)

    def patch(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.patch(url, **kwargs)

    def delete(self, url: str, **kwargs):
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return self._client.delete(url, **kwargs)


class ApiTestCase(unittest.TestCase):
    client: AuthenticatedTestClient | TestClient
    container: ApplicationContainer
    _client_context: TestClient
    auth_headers: dict[str, str]
    _raw_client: TestClient

    def setUp(self) -> None:
        raw_client, self.container, self._client_context = open_test_client()
        self._raw_client = raw_client
        plaintext = getattr(self.container, "_test_api_key_plaintext", None)
        if plaintext is None and self.container.authentication_service is not None:
            plaintext = bootstrap_test_api_key(self.container)
        self.auth_headers = auth_headers(plaintext) if plaintext else {}
        self.client = (
            AuthenticatedTestClient(raw_client, self.auth_headers)
            if self.auth_headers
            else raw_client
        )

    def tearDown(self) -> None:
        close_test_client(self._client_context, self.container)
