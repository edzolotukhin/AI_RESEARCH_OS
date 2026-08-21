from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from application.config import ApplicationConfig
from infrastructure.quantitative.storage.protected_file_dataset_storage import (
    ProtectedDatasetCorruptionError,
    ProtectedFileDatasetStorage,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class PropertyQVSharedProtectedDatasetStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.digest = Sha256DigestProvider()

    def storage(self, root: str, *, project: str = "project-a", run: str = "run-a"):
        return ProtectedFileDatasetStorage(
            root=root,
            project_id=project,
            run_id=run,
            digest_provider=self.digest,
        )

    def test_independent_api_and_worker_instances_share_opaque_authority(self):
        with tempfile.TemporaryDirectory() as root:
            api = self.storage(root)
            rows = (("Alice Example", "+49 123456", 1), ("Bob Example", None, 2))
            locator = api.put_parsed_rows("dataset-version", rows)

            worker = self.storage(root)
            self.assertEqual(worker.get_parsed_rows("dataset-version"), rows)
            self.assertTrue(locator.startswith("protected-dataset://"))
            self.assertNotIn(str(Path(root)), locator)

            for unauthorized in (
                self.storage(root, project="project-b"),
                self.storage(root, run="run-b"),
            ):
                with self.assertRaises(ProtectedDatasetCorruptionError):
                    unauthorized.get_parsed_rows("dataset-version")

    def test_recreation_preserves_payload_and_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            self.storage(root).put_parsed_rows("dataset-version", ((1, 2, 3),))
            self.assertEqual(
                self.storage(root).get_parsed_rows("dataset-version"),
                ((1, 2, 3),),
            )
            next(Path(root).rglob("rows-*.ql")).write_text("{}", encoding="utf-8")
            with self.assertRaises(ProtectedDatasetCorruptionError):
                self.storage(root).get_parsed_rows("dataset-version")

    def test_explicit_root_configuration_and_production_compose_are_shared_only_where_required(self):
        configured_root = "/configured/protected-root"
        with patch.dict(
            "os.environ",
            {"QUANTITATIVE_PROTECTED_STORAGE_ROOT": configured_root},
        ):
            configured = ApplicationConfig.from_env()
        self.assertEqual(configured.quantitative_protected_storage_root, configured_root)

        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        root = "/var/lib/ai_research_os/quantitative-protected"
        self.assertEqual(compose.count(f"QUANTITATIVE_PROTECTED_STORAGE_ROOT: {root}"), 2)
        self.assertEqual(compose.count(f"quantitative_protected_data:{root}"), 2)
        self.assertIn("  quantitative_protected_data:\n", compose)
        self.assertNotIn(f"postgres_data:{root}", compose)
        # Exactly two mounts means only the trusted API and worker services
        # receive this volume; n8n and PostgreSQL do not.
        self.assertEqual(compose.count("- quantitative_protected_data:"), 2)

        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "chown -R appuser:appuser /var/lib/ai_research_os",
            dockerfile,
        )
        self.assertLess(dockerfile.index("chown -R appuser:appuser"), dockerfile.index("USER appuser"))


if __name__ == "__main__":
    unittest.main()
