import unittest
from tools.acceptance_health import classify_worker_health
from tools.acceptance_health import parse_worker_state
from unittest.mock import patch
import contextlib
import io
import runpy
import subprocess

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

    def test_canonical_parser_preserves_state(self):
        raw = '{"Running":true,"Health":{"Log":[{"ExitCode":0,"Start":"start","End":"end"}]}}'
        from application.structured_output.json_validator import JsonValidator
        with patch.object(JsonValidator, 'validate', wraps=JsonValidator().validate) as validate:
            state = parse_worker_state(raw)
        validate.assert_called_once_with(raw)
        result = classify_worker_health(state)
        self.assertEqual(result['status'], 'HEALTHY')
        self.assertEqual((result['start'], result['end']), ('start', 'end'))

    def test_invalid_json_and_nonobject_state_fail_safely(self):
        for raw in ('secret-invalid', '[]', 'null', '"secret"', '1'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, '^Docker inspection unavailable$'):
                parse_worker_state(raw)

    def test_cli_invalid_response_is_execution_failure_without_payload(self):
        output = io.StringIO()
        with patch('sys.argv', ['acceptance_health', 'synthetic-worker']), patch(
            'subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'secret-invalid', '')
        ) as run, contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_result:
            runpy.run_path('tools/acceptance_health.py', run_name='__main__')
        self.assertEqual(exit_result.exception.code, 1)
        self.assertIn('EXECUTION FAILURE', output.getvalue())
        self.assertNotIn('secret', output.getvalue())
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
