from __future__ import annotations

import unittest

from application.persistence.records import ArtifactRecord

from tests.api.helpers import ApiTestCase


class ArtifactEndpointTests(ApiTestCase):

    def setUp(self) -> None:
        super().setUp()
        project = self.client.post("/projects", json={"name": "Artifact Project"}).json()
        self.project_id = project["id"]

    def test_empty_artifact_list(self) -> None:
        response = self.client.get(f"/projects/{self.project_id}/artifacts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    def test_persisted_artifact_metadata_is_returned(self) -> None:
        artifact = ArtifactRecord(
            id="artifact-1",
            project_id=self.project_id,
            artifact_type="report",
            title="Draft Report",
            content="Summary findings",
        )
        self.container.artifact_service.save_artifact(artifact)
        response = self.client.get(f"/projects/{self.project_id}/artifacts")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "artifact-1")
        self.assertEqual(items[0]["title"], "Draft Report")


if __name__ == "__main__":
    unittest.main()
