import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from application.operations.status import JobObservation, OperationsStatusService, sanitize_detail

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)

class OperationsStatusTests(unittest.TestCase):
    def service(self, root, **kwargs):
        worker = Path(root) / "worker.json"; backup = Path(root) / "backup.json"; storage = Path(root) / "storage"; storage.mkdir()
        worker.write_text(json.dumps({"observed_at": NOW.isoformat()}), encoding="utf-8")
        backup.write_text(json.dumps({"within_24h_policy": True}), encoding="utf-8")
        return OperationsStatusService(readiness=lambda: (True, "ready"), now=lambda: NOW,
            environment="pilot", worker_status_file=str(worker), backup_status_file=str(backup),
            storage_paths={"Protected artifacts": str(storage)}, **kwargs)

    def test_all_healthy_and_provider_disabled_is_not_broken(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {}, clear=True):
            snapshot = self.service(root).snapshot()
            self.assertEqual(snapshot.overall, "Healthy")
            self.assertEqual([c.status for c in snapshot.components if "provider" in c.name], ["Disabled", "Disabled"])

    def test_stale_job_is_critical_and_cross_in_jobs_remain_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            job = JobObservation("job-1", "presentation", "project-safe", "processing", NOW - timedelta(minutes=31))
            snapshot = self.service(root, jobs=lambda: [job] * 80).snapshot()
            self.assertEqual(snapshot.overall, "Critical"); self.assertEqual(snapshot.job_counts["stale"], 50)

    def test_failed_job_and_repeated_provider_failure_are_attention(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"SEARCH_API_KEY": "configured"}, clear=True):
            job = JobObservation("job-2", "qual-analysis", None, "failed", NOW, "safe_category")
            snapshot = self.service(root, jobs=lambda: [job], provider_failures={"Search provider": 3}).snapshot()
            self.assertEqual(snapshot.overall, "Attention"); self.assertEqual(snapshot.job_counts["failed"], 1)

    def test_worker_stale_backup_overdue_and_unknown_monitoring_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            Path(service.worker_status_file).write_text(json.dumps({"observed_at": (NOW - timedelta(seconds=91)).isoformat()}), encoding="utf-8")
            Path(service.backup_status_file).write_text(json.dumps({"within_24h_policy": False}), encoding="utf-8")
            self.assertEqual(service.snapshot().overall, "Critical")
            Path(service.worker_status_file).unlink()
            self.assertIn("Worker", service.snapshot().stop_conditions)

    def test_storage_thresholds(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("application.operations.status.shutil.disk_usage") as usage:
                usage.return_value = type("U", (), {"used": 95, "total": 100, "free": 5})()
                self.assertEqual(self.service(root).snapshot().overall, "Critical")

    def test_sanitization_withholds_sensitive_diagnostics(self):
        self.assertEqual(sanitize_detail("DATABASE_URL=postgresql://secret"), "Operational detail withheld.")
        self.assertEqual(sanitize_detail("lease exhausted"), "lease exhausted")

if __name__ == "__main__": unittest.main()
