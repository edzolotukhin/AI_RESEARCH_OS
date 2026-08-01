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

from tests.fixtures.planner_responses import VALID_PLANNER_JSON


def build_test_container(
    *,
    temp_dir: str | None = None,
    persistence_backend: str = "memory",
) -> ApplicationContainer:
    mock_llm = Mock()
    mock_llm.generate.return_value = LLMResponse(content=VALID_PLANNER_JSON)

    if temp_dir is None:
        temp_dir = tempfile.mkdtemp()

    container = create_application_container(
        config=ApplicationConfig(
            projects_root=temp_dir,
            persistence_backend=persistence_backend,
        ),
        overrides=ApplicationOverrides(llm_client=mock_llm),
    )
    container._test_llm_client = mock_llm  # test helper only
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


def build_test_client(
    container: ApplicationContainer | None = None,
) -> tuple[TestClient, ApplicationContainer]:
    """One-shot helper for smoke tests; prefer ApiTestCase for suites."""
    client, app_container, context = open_test_client(container)
    client._pf05_context = context
    return client, app_container


class ApiTestCase(unittest.TestCase):
    client: TestClient
    container: ApplicationContainer
    _client_context: TestClient

    def setUp(self) -> None:
        self.client, self.container, self._client_context = open_test_client()

    def tearDown(self) -> None:
        close_test_client(self._client_context, self.container)
