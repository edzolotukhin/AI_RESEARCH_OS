"""Offline-only HTTP/error visibility regressions; providers always mocked."""
import contextlib
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from domain.research_brief import ResearchBrief
from tests.api.helpers import ApiTestCase
from tools.acceptance_http import AcceptanceHttpError, MAX_ERROR_BYTES, error_diagnostic, post_form


def failure(body, content_type="application/json", **headers):
    message = Message()
    message["Content-Type"] = content_type
    for key, value in headers.items():
        message[key] = value
    return HTTPError("http://localhost/design/generate", 422, "Unprocessable Entity", message, io.BytesIO(body.encode()))


class AcceptanceHttpDiagnosticTests(unittest.TestCase):
    def test_json_diagnostics_use_shared_validator_then_redact(self):
        from application.structured_output.json_validator import JsonValidator
        with patch("tools.acceptance_http.JsonValidator", wraps=JsonValidator) as validator:
            record = error_diagnostic(failure('{"detail":"Authorization: Bearer private-value"}',
                **{"X-Correlation-ID": "correlation-123"}), endpoint="/design/generate", stage="generate")
        validator.assert_called_once_with()
        self.assertEqual(record["http_status"], 422)
        self.assertEqual(record["stage"], "generate")
        self.assertEqual(record["x-correlation-id"], "correlation-123")
        self.assertNotIn("private-value", json.dumps(record))

    def test_recursion_error_omits_body_without_disclosing_it(self):
        with patch("tools.acceptance_http.JsonValidator.validate", side_effect=RecursionError("PRIVATE")):
            record = error_diagnostic(failure('{"detail":"PRIVATE"}'), endpoint="/x", stage="generate")
        self.assertEqual(record["body_omitted"], "invalid_json")
        self.assertNotIn("PRIVATE", json.dumps(record))

    def test_direct_cli_import_from_outside_repository(self):
        script = Path(__file__).resolve().parents[3] / "tools" / "prf08l_ui.py"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--diagnostics", result.stdout)

    def test_structured_validation_retained_without_input_or_context(self):
        error = failure(json.dumps({"detail": [{"loc": ["body", "design_id"], "type": "missing", "msg": "Field required", "input": "PRIVATE INPUT", "ctx": {"token": "PRIVATE TOKEN"}}], "payload": "PRIVATE PAYLOAD"}), **{"X-Request-ID": "request-123"})
        record = error_diagnostic(error, endpoint="http://user:pass@localhost/design/generate?token=PRIVATE", stage="generate")
        self.assertEqual(record["http_status"], 422)
        self.assertEqual(record["endpoint"], "/design/generate")
        self.assertEqual(record["x-request-id"], "request-123")
        self.assertEqual(record["validation"]["detail"][0], {"loc": ["body", "design_id"], "type": "missing", "msg": "Field required"})
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertNotIn("pass", json.dumps(record))

    def test_html_alert_only_and_secret_redaction(self):
        body = '<html><h1>PRIVATE PROJECT</h1><div class="alert">Invalid RQ: RQ5. Authorization: Bearer abc-secret; password="private password"; sk-fakeProviderKey; tvly-fakeKey; airos_fake_key <script>PRIVATE SCRIPT</script></div><input value="PRIVATE INPUT"></html>'
        record = error_diagnostic(failure(body, "text/html", **{"Set-Cookie": "PRIVATE COOKIE"}), endpoint="/design/generate", stage="generate")
        text = json.dumps(record)
        self.assertIn("Invalid RQ: RQ5", text)
        for secret in ("PRIVATE", "abc-secret", "private password", "sk-fakeProviderKey", "tvly-fakeKey", "airos_fake_key", "Authorization"):
            self.assertNotIn(secret, text)

    def test_provider_preview_is_not_recorded(self):
        record = error_diagnostic(failure(json.dumps({"message": "Invalid output; preview=arbitrary private provider response"})), endpoint="/x", stage="generate")
        self.assertEqual(record["validation"]["message"], "Invalid output;")

    def test_unknown_body_is_omitted(self):
        record = error_diagnostic(failure("PRIVATE BODY", "text/plain"), endpoint="/x", stage="generate")
        self.assertEqual(record["body_omitted"], "unsupported_content_type")
        self.assertNotIn("PRIVATE", json.dumps(record))

    def test_oversize_error_is_omitted(self):
        record = error_diagnostic(failure("x"*(MAX_ERROR_BYTES+1)), endpoint="/x", stage="generate")
        self.assertEqual(record["body_omitted"], "size_limit")

    def test_invalid_json_is_not_dumped(self):
        record = error_diagnostic(failure('{"token":"PRIVATE'), endpoint="/x", stage="generate")
        self.assertEqual(record["body_omitted"], "invalid_json")
        self.assertNotIn("PRIVATE", json.dumps(record))

    def test_body_read_failure_still_records_status(self):
        error = failure("")
        with patch.object(error, "read", side_effect=OSError("PRIVATE")):
            record = error_diagnostic(error, endpoint="/x", stage="generate")
        self.assertEqual(record["http_status"], 422)
        self.assertEqual(record["body_omitted"], "read_error")
        self.assertNotIn("PRIVATE", json.dumps(record))

    def test_cli_wires_diagnostic_file_without_retry(self):
        from tools.prf08l_ui import main
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", side_effect=failure('{"detail":"Invalid design"}')) as send, contextlib.redirect_stderr(io.StringIO()):
            path = Path(directory)/"error.log"
            with patch("sys.argv", ["prf08l_ui.py", "generate", "--project", "offline-id", "--diagnostics", str(path)]):
                with self.assertRaises(AcceptanceHttpError):
                    main()
            record = json.loads(path.read_text())
            self.assertEqual(record["stage"], "generate")
            self.assertEqual(record["endpoint"], "/ui/projects/offline-id/design/generate")
            self.assertEqual(record["validation"], {"detail": "Invalid design"})
            send.assert_called_once()

    def test_persisted_failure_is_redacted_and_request_not_retried(self):
        error = failure(json.dumps({"message": "configured OPAQUE_ENV_SECRET rejected; token=FORM_SECRET", "Authorization": "HIDDEN", "input": "PRIVATE BODY"}))
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": "OPAQUE_ENV_SECRET"}), patch("urllib.request.urlopen", side_effect=error) as send, contextlib.redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory)/"diagnostic.log"
            with self.assertRaises(AcceptanceHttpError) as caught:
                post_form("http://localhost/x?token=PRIVATE", {"token": "FORM_SECRET"}, stage="generate", diagnostic_path=path)
            send.assert_called_once()
            saved = path.read_text()
            self.assertEqual(json.loads(saved), caught.exception.diagnostic)
            for secret in ("OPAQUE_ENV_SECRET", "FORM_SECRET", "PRIVATE", "HIDDEN"):
                self.assertNotIn(secret, saved + stderr.getvalue() + str(caught.exception))

    def test_success_empty_form_follows_normal_path_without_error_file(self):
        response = Mock(status=200, url="http://localhost/ui/projects/test/design")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", return_value=response) as send:
            path = Path(directory)/"diagnostic.log"
            self.assertEqual(post_form("http://localhost/ui/projects/test/design/generate", {}, stage="generate", diagnostic_path=path), (200, response.url))
            request = send.call_args.args[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.data, b"")
            self.assertFalse(path.exists())
            send.assert_called_once()


class DesignRequestPathTests(ApiTestCase):
    def prepare(self):
        from api.ui.principal import resolve_ui_principal
        project = self.container.project_service.create_project(
            "Offline request reconstruction", project_id="f8b634b0-dae6-44a1-86ed-cc1c00726e9f",
            owner_principal_id=resolve_ui_principal(self.container).principal_id, selected_methods=("DESK",),
        )
        self.container.project_planning_service.save_brief(project, ResearchBrief(
            title="Offline public charging review", business_question="Which public charging evidence supports site due diligence?",
            objectives=["Compare documented installed capacity", "Identify limitations in public observations"],
            geography=["United Kingdom"], timeframe="1 January 2025 to 1 July 2026", language="en",
        ))
        return project.id

    def test_reconstructed_empty_request_reaches_model_boundary(self):
        project_id = self.prepare()
        class OfflineBoundaryReached(RuntimeError):
            pass
        with patch.object(self.container._test_llm_client, "generate", side_effect=OfflineBoundaryReached("offline stop")) as generate:
            response = self.client.post(f"/ui/projects/{project_id}/design/generate", content=b"", headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
            self.assertEqual(response.status_code, 500)
            generate.assert_called_once()
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project_id), [])

    def test_valid_request_saves_draft_without_activation(self):
        project_id = self.prepare()
        response = self.client.post(f"/ui/projects/{project_id}/design/generate", content=b"", headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self.container.project_service.get_project(project_id).research_design_status, "DRAFT")
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project_id), [])

    def test_representative_product_validation_422_is_retained(self):
        project_id = self.prepare()
        with patch.object(self.container.project_planning_service.planner, "run", side_effect=ValueError("ResearchQuestion without a valid InformationNeed: RQ5")):
            response = self.client.post(f"/ui/projects/{project_id}/design/generate", content=b"", follow_redirects=False)
        self.assertEqual(response.status_code, 422)
        record = error_diagnostic(failure(response.text, response.headers["content-type"]), endpoint=f"/ui/projects/{project_id}/design/generate", stage="generate")
        self.assertEqual(record["validation"]["messages"], ["ResearchQuestion without a valid InformationNeed: RQ5"])
        self.assertNotIn("Offline request reconstruction", json.dumps(record))
        self.assertEqual(self.container.workflow_service.list_workflow_runs_for_project(project_id), [])


if __name__ == "__main__":
    unittest.main()
