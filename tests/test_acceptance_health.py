import unittest
from tools.acceptance_health import classify_worker_health

class HealthClassificationTests(unittest.TestCase):
    def probe(self, code, end, output=""):
        return classify_worker_health({"Running": True, "Health": {"Log": [{
            "Start": "2026-09-27T00:00:00Z", "End": end,
            "ExitCode": code, "Output": output}]}})

    def test_slow_success_within_fifteen_seconds(self):
        self.assertEqual(self.probe(0, "2026-09-27T00:00:11Z")["status"], "HEALTHY")

    def test_timeout_after_fifteen_seconds(self):
        self.assertEqual(self.probe(-1, "2026-09-27T00:00:16Z", "Health check exceeded timeout (15s)")["status"], "HEALTHCHECK TIMEOUT")

    def test_application_failure(self):
        self.assertEqual(self.probe(1, "2026-09-27T00:00:01Z")["status"], "APPLICATION FAILURE")

    def test_success(self):
        self.assertEqual(self.probe(0, "2026-09-27T00:00:01Z")["status"], "HEALTHY")

    def test_exec_failure_not_timeout(self):
        self.assertEqual(self.probe(-1, "2026-09-27T00:00:01Z", "exec failed")["status"], "EXECUTION FAILURE")

    def test_stopped(self):
        self.assertEqual(classify_worker_health({"Running": False, "ExitCode":255})["status"], "CONTAINER NOT RUNNING")

    def test_no_sensitive_output(self):
        self.assertNotIn("secret", str(self.probe(1, "now", "secret")))
