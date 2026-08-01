from __future__ import annotations

import unittest

from tests.api.helpers import ApiTestCase


class OpenAPISmokeTests(ApiTestCase):

    def test_openapi_json_contains_expected_routes(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        paths = schema["paths"]
        for path in (
            "/health",
            "/ready",
            "/projects",
            "/projects/{project_id}",
            "/projects/{project_id}/research",
            "/workflow-runs/{run_id}",
            "/workflow-runs/{run_id}/resume",
            "/workflow-runs/{run_id}/results",
            "/workflow-runs/{run_id}/logs",
        ):
            self.assertIn(path, paths)

    def test_operation_ids_are_unique(self) -> None:
        schema = self.client.get("/openapi.json").json()
        operation_ids: list[str] = []
        for path_item in schema["paths"].values():
            for operation in path_item.values():
                if isinstance(operation, dict) and "operationId" in operation:
                    operation_ids.append(operation["operationId"])
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_dto_names_do_not_expose_domain_models(self) -> None:
        schema = self.client.get("/openapi.json").json()
        model_names = set(schema.get("components", {}).get("schemas", {}))
        forbidden = {"Project", "WorkflowRun", "WorkflowContext", "ArtifactRecord"}
        self.assertFalse(model_names.intersection(forbidden))

    def test_start_research_documents_synchronous_execution(self) -> None:
        schema = self.client.get("/openapi.json").json()
        operation = schema["paths"]["/projects/{project_id}/research"]["post"]
        self.assertEqual(operation["operationId"], "startResearch")
        self.assertIn("200", operation["responses"])
        self.assertNotIn("202", operation["responses"])
        description = " ".join(
            [
                operation.get("summary", ""),
                operation.get("description", ""),
                schema["info"].get("description", ""),
            ]
        ).lower()
        self.assertIn("synchronous", description)

    def test_docs_and_redoc_are_available(self) -> None:
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/redoc").status_code, 200)


if __name__ == "__main__":
    unittest.main()
