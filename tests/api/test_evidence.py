from __future__ import annotations

import tempfile
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.exceptions.capability_not_implemented_error import (
    CapabilityNotImplementedError,
)

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock


class EvidenceApiTests(unittest.TestCase):
    def test_owner_can_list_and_get_evidence_after_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            container = create_application_container(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    persistence_backend="memory",
                    background_execution_mode="embedded",
                    deterministic_stage_executors=False,
                    search_provider="deterministic",
                    evidence_extractor="deterministic",
                    analysis_engine="deterministic",
                    report_engine="deterministic",
                ),
                overrides=ApplicationOverrides(
                    llm_client=create_brief_aligned_llm_mock(),
                ),
            )
            bootstrap_test_api_key(container)
            raw, _, context = open_test_client(container)
            try:
                client = AuthenticatedTestClient(
                    raw,
                    auth_headers(container._test_api_key_plaintext),
                )
                project_id = client.post(
                    "/projects",
                    json={"name": "Evidence API Project"},
                ).json()["id"]
                started = client.post(
                    f"/projects/{project_id}/research",
                    json={"brief": BRIEF},
                ).json()
                run_id = started["run_id"]
                try:
                    drain_background_runs(container)
                except CapabilityNotImplementedError:
                    pass
                listed = client.get(
                    f"/projects/{project_id}/evidence",
                    params={"workflow_run_id": run_id},
                )
                self.assertEqual(listed.status_code, 200)
                items = listed.json()["items"]
                self.assertGreater(len(items), 0)
                evidence_id = items[0]["id"]
                detail = client.get(f"/evidence/{evidence_id}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["workflow_run_id"], run_id)
            finally:
                close_test_client(context, container)
                container.shutdown()

    def test_foreign_principal_cannot_read_project_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            owner = create_application_container(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    persistence_backend="memory",
                    background_execution_mode="embedded",
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=create_brief_aligned_llm_mock(),
                ),
            )
            bootstrap_test_api_key(owner, name="owner")
            owner_raw, _, owner_context = open_test_client(owner)
            foreign = create_application_container(
                config=ApplicationConfig(
                    projects_root=temp_dir,
                    persistence_backend="memory",
                    background_execution_mode="embedded",
                    deterministic_stage_executors=True,
                ),
                overrides=ApplicationOverrides(
                    llm_client=create_brief_aligned_llm_mock(),
                ),
            )
            bootstrap_test_api_key(foreign, name="foreign")
            foreign_raw, _, foreign_context = open_test_client(foreign)
            try:
                owner_client = AuthenticatedTestClient(
                    owner_raw,
                    auth_headers(owner._test_api_key_plaintext),
                )
                foreign_client = AuthenticatedTestClient(
                    foreign_raw,
                    auth_headers(foreign._test_api_key_plaintext),
                )
                project_id = owner_client.post(
                    "/projects",
                    json={"name": "Owned Project"},
                ).json()["id"]
                response = foreign_client.get(f"/projects/{project_id}/evidence")
                self.assertEqual(response.status_code, 404)
            finally:
                close_test_client(owner_context, owner)
                close_test_client(foreign_context, foreign)
                owner.shutdown()
                foreign.shutdown()


if __name__ == "__main__":
    unittest.main()
