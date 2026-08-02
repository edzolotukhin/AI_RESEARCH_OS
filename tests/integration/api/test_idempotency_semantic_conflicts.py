"""Idempotency conflict tests for semantic brief field changes."""

from __future__ import annotations

import concurrent.futures
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)

from api.app import create_fastapi_app

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import close_test_client, open_test_client
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    get_test_database_url,
)


class IdempotencySemanticConflictTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        self.mock_llm = create_brief_aligned_llm_mock()
        self.container = create_application_container(
            config=ApplicationConfig(
                persistence_backend="postgresql",
                database_url=get_test_database_url(),
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(llm_client=self.mock_llm),
        )
        bootstrap_test_api_key(self.container)
        self.addCleanup(self.container.shutdown)
        client, _, context = open_test_client(self.container)
        self.addCleanup(lambda: close_test_client(context, self.container))
        self.client = client
        self.auth_headers = auth_headers(self.container._test_api_key_plaintext)
        self.project_id = client.post(
            "/projects",
            json={"name": "Idempotency Semantic Project"},
            headers=self.auth_headers,
        ).json()["id"]

    def _assert_fingerprint_changes(self, modified_brief: dict) -> None:
        original = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=BRIEF,
        )
        changed = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=modified_brief,
        )
        self.assertNotEqual(original, changed)

    def _sequential_conflict(self, modified_brief: dict) -> None:
        self._assert_fingerprint_changes(modified_brief)
        headers = {"Idempotency-Key": f"seq-{modified_brief.get('title', 'x')}"}
        first = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": BRIEF},
            headers={**headers, **self.auth_headers},
        )
        self.assertEqual(first.status_code, 202)
        second = self.client.post(
            f"/projects/{self.project_id}/research",
            json={"brief": modified_brief},
            headers={**headers, **self.auth_headers},
        )
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(self.mock_llm.generate.call_count, 1)

    def _concurrent_conflict(self, modified_brief: dict) -> None:
        self._assert_fingerprint_changes(modified_brief)
        headers = {
            "Idempotency-Key": f"concurrent-{modified_brief.get('title', 'x')}",
            **self.auth_headers,
        }

        def _submit(body: dict):
            app = create_fastapi_app(container=self.container)
            from fastapi.testclient import TestClient

            with TestClient(app) as thread_client:
                return thread_client.post(
                    f"/projects/{self.project_id}/research",
                    json=body,
                    headers=headers,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = [
                pool.submit(_submit, {"brief": BRIEF}).result(),
                pool.submit(_submit, {"brief": modified_brief}).result(),
            ]

        statuses = sorted(response.status_code for response in responses)
        self.assertEqual(statuses, [202, 409], [response.text for response in responses])
        accepted = [response for response in responses if response.status_code == 202]
        conflict = [response for response in responses if response.status_code == 409]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(conflict), 1)
        self.assertEqual(conflict[0].json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(self.mock_llm.generate.call_count, 1)

    def test_objectives_change_sequential_conflict_before_planning(self) -> None:
        modified = {
            **BRIEF,
            "objectives": ["Identify competitors.", "Estimate market size."],
        }
        self._sequential_conflict(modified)

    def test_objectives_change_concurrent_conflict_before_planning(self) -> None:
        modified = {
            **BRIEF,
            "objectives": ["Identify competitors.", "Estimate market size."],
        }
        self._concurrent_conflict(modified)

    def test_geography_change_sequential_conflict_before_planning(self) -> None:
        modified = {**BRIEF, "geography": ["France", "Italy"]}
        self._sequential_conflict(modified)

    def test_geography_change_concurrent_conflict_before_planning(self) -> None:
        modified = {**BRIEF, "geography": ["France", "Italy"]}
        self._concurrent_conflict(modified)

    def test_timeframe_change_sequential_conflict_before_planning(self) -> None:
        modified = {**BRIEF, "timeframe": "2024-2025"}
        self._sequential_conflict(modified)

    def test_timeframe_change_concurrent_conflict_before_planning(self) -> None:
        modified = {**BRIEF, "timeframe": "2024-2025"}
        self._concurrent_conflict(modified)


if __name__ == "__main__":
    unittest.main()
