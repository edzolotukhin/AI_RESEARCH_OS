from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.container import ApplicationContainer
from domain.ai.llm_response import LLMResponse

from api.app import create_fastapi_app

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock


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
    return container.worker_execution_service.drain_runnable_runs(
        worker_id,
        max_runs=max_runs,
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
