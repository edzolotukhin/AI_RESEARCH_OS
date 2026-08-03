"""Static and native n8n workflow validation for product acceptance."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from tests.integration.n8n.workflow_contract_helpers import (
    ORCHESTRATION_VAR_NAMES,
    artifact_fetch_uses_process_poll_response,
    exported_workflow_by_name,
    load_workflow,
    orchestration_assignment_names,
    resolve_artifact_content_url,
    resolve_artifact_metadata_url,
    submit_research_uses_brief_input,
    workflow_contains_stale_brief_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / "examples" / "n8n" / "desk_research_product_acceptance.json"

ALLOWED_NODE_PREFIXES = (
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.set",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.if",
    "n8n-nodes-base.wait",
    "n8n-nodes-base.code",
)

REQUIRED_ENV_REFS = (
    "AI_RESEARCH_OS_API_URL",
    "AI_RESEARCH_OS_API_KEY",
    "N8N_POLL_INTERVAL_SECONDS",
    "N8N_MAX_POLL_ATTEMPTS",
    "N8N_RESEARCH_BRIEF_JSON",
)

SECRET_PATTERNS = (
    re.compile(r"airos_[A-Za-z0-9_-]{20,}"),
    re.compile(r"postgresql\+psycopg://"),
    re.compile(r"ai_research_os_dev"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
)

TERMINAL_OUTCOME_NODES = {
    "Success Payload",
    "Rejected Payload",
    "Failed Payload",
    "Contract Failure Payload",
    "Poll Timeout Payload",
}

ARTIFACT_SUCCESS_NODES = {
    "Fetch Artifact Metadata",
    "Fetch Artifact Content",
}


class N8nWorkflowJsonValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load_workflow()
        self.raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.node_names = {node["name"] for node in self.workflow["nodes"]}

    def test_workflow_file_exists_and_parses(self) -> None:
        self.assertEqual(self.workflow["name"], "Desk Research — Product Acceptance")
        self.assertIn("nodes", self.workflow)
        self.assertIn("connections", self.workflow)

    def test_node_types_are_recognized_base_nodes(self) -> None:
        for node in self.workflow["nodes"]:
            node_type = node["type"]
            self.assertTrue(
                node_type.startswith(ALLOWED_NODE_PREFIXES),
                f"Unexpected node type: {node_type} ({node['name']})",
            )

    def test_connections_reference_existing_nodes(self) -> None:
        for source, connection in self.workflow["connections"].items():
            self.assertIn(source, self.node_names, f"Unknown connection source: {source}")
            for outputs in connection.get("main", []):
                for target in outputs:
                    self.assertIn(
                        target["node"],
                        self.node_names,
                        f"Unknown connection target: {target['node']}",
                    )

    def test_required_environment_references_present(self) -> None:
        for env_name in REQUIRED_ENV_REFS:
            self.assertIn(env_name, self.raw, f"Missing env reference: {env_name}")

    def test_no_embedded_secrets_or_credentials(self) -> None:
        self.assertNotIn("credentials", self.raw.lower())
        for pattern in SECRET_PATTERNS:
            self.assertIsNone(
                pattern.search(self.raw),
                f"Possible secret matched: {pattern.pattern}",
            )

    def test_bounded_polling_nodes_exist(self) -> None:
        required = {
            "Prepare Poll Loop",
            "Process Poll Response",
            "Max Poll Attempts?",
            "Poll Timeout Payload",
            "Continue Poll Loop",
        }
        self.assertTrue(required.issubset(self.node_names))

    def test_terminal_failure_branches_do_not_fetch_artifacts(self) -> None:
        for source, connection in self.workflow["connections"].items():
            if source not in TERMINAL_OUTCOME_NODES - {"Success Payload"}:
                continue
            for branch in connection.get("main", []):
                for target in branch:
                    self.assertNotIn(
                        target["node"],
                        ARTIFACT_SUCCESS_NODES,
                        f"{source} must not fetch artifacts on failure",
                    )

    def test_success_path_reaches_artifact_fetch(self) -> None:
        reachable = _reachable_from("Approved Final Artifact?", self.workflow["connections"])
        self.assertIn("Fetch Artifact Metadata", reachable)
        self.assertIn("Fetch Artifact Content", reachable)
        self.assertIn("Success Payload", reachable)

    def test_poll_timeout_does_not_reach_success_output(self) -> None:
        reachable = _reachable_from("Poll Timeout Payload", self.workflow["connections"])
        self.assertNotIn("Success Payload", reachable)
        self.assertNotIn("Fetch Artifact Content", reachable)

    def test_orchestration_vars_use_assignments_not_legacy_defaults(self) -> None:
        names = orchestration_assignment_names(self.workflow)
        self.assertEqual(names, list(ORCHESTRATION_VAR_NAMES))
        self.assertNotIn("my_field_1", self.raw)
        self.assertNotIn("my_field_2", self.raw)
        set_node = next(
            node for node in self.workflow["nodes"] if node["name"] == "Set Orchestration Vars"
        )
        self.assertEqual(set_node["typeVersion"], 3.4)
        self.assertIn("assignments", set_node["parameters"])

    def test_research_brief_is_external_input_not_hardcoded(self) -> None:
        self.assertIn("Parse Research Brief", self.node_names)
        self.assertTrue(submit_research_uses_brief_input(self.workflow))
        self.assertFalse(workflow_contains_stale_brief_payload(self.workflow))
        submit_body = json.dumps(
            next(node for node in self.workflow["nodes"] if node["name"] == "Submit Research")[
                "parameters"
            ]
        )
        self.assertNotIn('"client"', submit_body)

    def test_process_poll_response_preserves_final_artifact_id(self) -> None:
        code = next(
            node for node in self.workflow["nodes"] if node["name"] == "Process Poll Response"
        )["parameters"]["jsCode"]
        for field in (
            "final_artifact_id",
            "final_artifact_available",
            "final_review_verdict",
            "api_url",
            "run_id",
        ):
            self.assertIn(field, code)

    def test_artifact_fetch_uses_process_poll_response_identity(self) -> None:
        self.assertTrue(
            artifact_fetch_uses_process_poll_response(self.workflow, "Fetch Artifact Metadata")
        )
        self.assertTrue(
            artifact_fetch_uses_process_poll_response(self.workflow, "Fetch Artifact Content")
        )
        self.assertNotIn("final.artifact_id", self.raw)

    def test_artifact_metadata_url_resolves_real_id_not_null(self) -> None:
        url = resolve_artifact_metadata_url(
            api_url="http://api:8000",
            final_artifact_id="artifact-123",
        )
        self.assertEqual(url, "http://api:8000/artifacts/artifact-123")
        self.assertNotIn("/artifacts/null", url)

    def test_artifact_content_url_matches_metadata_identity(self) -> None:
        metadata_url = resolve_artifact_metadata_url(
            api_url="http://api:8000",
            final_artifact_id="artifact-123",
        )
        content_url = resolve_artifact_content_url(
            api_url="http://api:8000",
            final_artifact_id="artifact-123",
        )
        self.assertEqual(content_url, metadata_url + "/content")


def _reachable_from(start: str, connections: dict) -> set[str]:
    """Nodes reachable forward from connection sources named start."""
    reachable: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for branch in connections.get(current, {}).get("main", []):
            for target in branch:
                queue.append(target["node"])
    return reachable


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(_docker_available(), "Docker is required for native n8n import validation.")
class N8nNativeImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.container_name = "ai_research_os_n8n_acceptance"
        cls.project_name = "ai_research_os_n8n_acceptance_test"
        compose_files = [
            "-f",
            str(REPO_ROOT / "docker-compose.n8n-import-test.yml"),
        ]
        cls.compose_base = ["docker", "compose", *compose_files, "-p", cls.project_name]

        subprocess.run(
            ["docker", "rm", "-f", cls.container_name],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        subprocess.run(
            [*cls.compose_base, "up", "-d", "n8n"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        cls._wait_for_n8n()

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(
            [*cls.compose_base, "down", "-v"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )

    @classmethod
    def _wait_for_n8n(cls) -> None:
        import time
        import urllib.request

        url = "http://localhost:5679/healthz"
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(3)
        raise TimeoutError("n8n health check did not become ready")

    def test_native_cli_import_succeeds(self) -> None:
        container = self.container_name
        target = "/tmp/desk_research_product_acceptance.json"

        copy = subprocess.run(
            [
                "docker",
                "cp",
                str(WORKFLOW_PATH),
                f"{container}:{target}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        self.assertEqual(copy.returncode, 0)

        import_result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "node",
                container,
                "n8n",
                "import:workflow",
                f"--input={target}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(
            import_result.returncode,
            0,
            msg=import_result.stdout + import_result.stderr,
        )

        export_path = "/tmp/exported-workflows.json"
        export_result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "node",
                container,
                "n8n",
                "export:workflow",
                "--all",
                f"--output={export_path}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(export_result.returncode, 0, msg=export_result.stderr)

        read_export = subprocess.run(
            ["docker", "exec", container, "cat", export_path],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        exported = json.loads(read_export.stdout)
        if isinstance(exported, list):
            names = [item.get("name", "") for item in exported]
        else:
            names = [exported.get("name", "")]
        self.assertTrue(
            any("Desk Research" in name for name in names),
            msg=f"Expected workflow name in export, got: {names}",
        )

        workflow = exported_workflow_by_name(exported, "Desk Research")
        exported_raw = json.dumps(workflow)
        self.assertNotIn("my_field_1", exported_raw)
        self.assertNotIn("my_field_2", exported_raw)
        self.assertEqual(
            orchestration_assignment_names(workflow),
            list(ORCHESTRATION_VAR_NAMES),
        )
        self.assertTrue(submit_research_uses_brief_input(workflow))
        self.assertFalse(workflow_contains_stale_brief_payload(workflow))
        self.assertTrue(
            artifact_fetch_uses_process_poll_response(workflow, "Fetch Artifact Metadata")
        )
        self.assertTrue(
            artifact_fetch_uses_process_poll_response(workflow, "Fetch Artifact Content")
        )
        self.assertNotIn("final.artifact_id", exported_raw)


if __name__ == "__main__":
    unittest.main()
