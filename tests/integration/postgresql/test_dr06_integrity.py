"""DR-06 artifact content integrity and citation completeness tests."""

from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.report.deduplication import compute_content_checksum

from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    drain_background_runs,
    open_test_client,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class Dr06IntegrityPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_artifact_checksum_content_and_foreign_access(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(container._test_api_key_plaintext),
        )

        project_id = client.post("/projects", json={"name": "Integrity Project"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]
        drain_background_runs(container)

        artifact_id = client.get(f"/workflow-runs/{run_id}/artifacts").json()["items"][0]["id"]
        content_payload = client.get(f"/artifacts/{artifact_id}/content").json()
        self.assertEqual(
            content_payload["content_checksum"],
            compute_content_checksum(content_payload["content"]),
        )
        self.assertNotIn("path", content_payload)
        self.assertNotIn("storage", str(content_payload).lower())

        container.shutdown()
        fresh = create_application_container(
            config=postgresql_application_config(report_engine="deterministic"),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        self.addCleanup(fresh.shutdown)
        reloaded = fresh.artifact_service.get_artifact(artifact_id)
        self.assertEqual(reloaded.content, content_payload["content"])
        self.assertEqual(
            reloaded.content_checksum,
            compute_content_checksum(reloaded.content),
        )

        foreign = client.get(f"/artifacts/not-a-real-id/content")
        self.assertEqual(foreign.status_code, 404)

    def test_citation_registry_resolves_through_evidence_to_source(self) -> None:
        mock_llm = create_brief_aligned_llm_mock()
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False,
                search_provider="deterministic",
                evidence_extractor="deterministic",
                analysis_engine="deterministic",
                report_engine="deterministic",
            ),
            overrides=ApplicationOverrides(llm_client=mock_llm),
        )
        bootstrap_test_api_key(container)
        self.addCleanup(container.shutdown)
        raw_client, _, context = open_test_client(container)
        self.addCleanup(lambda: close_test_client(context, container))
        client = AuthenticatedTestClient(
            raw_client,
            auth_headers(container._test_api_key_plaintext),
        )

        project_id = client.post("/projects", json={"name": "Citation Project"}).json()["id"]
        run_id = client.post(
            f"/projects/{project_id}/research",
            json={"brief": BRIEF},
        ).json()["run_id"]
        drain_background_runs(container)

        report = client.get(
            f"/projects/{project_id}/reports",
            params={"workflow_run_id": run_id},
        ).json()["items"][0]
        evidence_items = {
            item["id"]: item
            for item in client.get(
                f"/projects/{project_id}/evidence",
                params={"workflow_run_id": run_id},
            ).json()["items"]
        }
        source_items = {
            item["id"]: item
            for item in client.get(
                f"/projects/{project_id}/sources",
                params={"workflow_run_id": run_id},
            ).json()["items"]
        }
        registry = report["citation_registry"]
        seen_citations: set[str] = set()

        for section in report["sections"]:
            for citation_id in section["citation_ids"]:
                self.assertIn(citation_id, registry)
                entry = registry[citation_id]
                source_id = entry["source_id"]
                self.assertIn(source_id, source_items)
                seen_citations.add(citation_id)

                section_evidence = set(section.get("evidence_refs", []))
                for finding_id in section.get("finding_refs", []):
                    finding = next(
                        item
                        for item in client.get(
                            f"/projects/{project_id}/findings",
                            params={"workflow_run_id": run_id},
                        ).json()["items"]
                        if item["id"] == finding_id
                    )
                    section_evidence.update(finding["evidence_refs"])

                linked = False
                for evidence_id in section_evidence:
                    evidence = evidence_items.get(evidence_id)
                    if evidence is not None and evidence["source_id"] == source_id:
                        linked = True
                        break
                self.assertTrue(
                    linked,
                    f"Citation {citation_id} must trace to section evidence chain",
                )

        self.assertTrue(seen_citations)
        for citation_id, entry in registry.items():
            self.assertTrue(citation_id.startswith("S"))
            self.assertIn(entry["source_id"], source_items)


if __name__ == "__main__":
    unittest.main()
