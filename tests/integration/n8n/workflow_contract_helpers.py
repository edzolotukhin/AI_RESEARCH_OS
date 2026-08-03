"""Helpers for validating canonical n8n workflow JSON semantics."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / "examples" / "n8n" / "desk_research_product_acceptance.json"

ORCHESTRATION_VAR_NAMES = (
    "correlation_id",
    "idempotency_key",
    "api_url",
    "poll_interval_seconds",
    "max_poll_attempts",
)

STALE_BRIEF_MARKERS = (
    "Brand Health 2026",
    "Purina",
    "Germany",
    "Serbia Microgreens",
)

LEGACY_ARTIFACT_EXPRESSIONS = (
    "final.artifact_id",
    "$json.final.artifact_id",
)

TERMINAL_OUTCOME_BY_ROUTE = {
    "failed": "Failed Payload",
    "rejected": "Rejected Payload",
    "success": "Fetch Artifact Metadata",
    "contract_failure": "Contract Failure Payload",
}


def load_workflow() -> dict:
    payload = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow["nodes"]:
        if node["name"] == name:
            return node
    raise KeyError(f"Node not found: {name}")


def node_parameters_text(workflow: dict, name: str) -> str:
    return json.dumps(node_by_name(workflow, name).get("parameters", {}))


def orchestration_assignment_names(workflow: dict) -> list[str]:
    params = node_by_name(workflow, "Set Orchestration Vars").get("parameters", {})
    assignments = params.get("assignments", {}).get("assignments", [])
    return [item["name"] for item in assignments if "name" in item]


def resolve_artifact_metadata_url(*, api_url: str, final_artifact_id: str | None) -> str:
    """Mirror canonical n8n Fetch Artifact Metadata URL construction."""
    if not final_artifact_id:
        raise ValueError("final_artifact_id is required for artifact metadata fetch")
    return f"{api_url.rstrip('/')}/artifacts/{final_artifact_id}"


def resolve_artifact_content_url(*, api_url: str, final_artifact_id: str | None) -> str:
    """Mirror canonical n8n Fetch Artifact Content URL construction."""
    if not final_artifact_id:
        raise ValueError("final_artifact_id is required for artifact content fetch")
    return f"{api_url.rstrip('/')}/artifacts/{final_artifact_id}/content"


def resolve_terminal_outcome(poll: dict) -> str:
    """
    Mirror authoritative terminal routing in the canonical n8n workflow.
    """
    status = poll.get("status")
    verdict = poll.get("final_review_verdict")
    artifact_available = bool(poll.get("final_artifact_available"))
    artifact_id = poll.get("final_artifact_id")

    if status == "failed":
        return "failed"
    if verdict == "reject":
        return "rejected"
    if (
        status == "completed"
        and verdict == "approve"
        and artifact_available
        and artifact_id
    ):
        return "success"
    if poll.get("is_terminal"):
        return "contract_failure"
    return "pending"


def terminal_route_target_node(outcome: str) -> str:
    return TERMINAL_OUTCOME_BY_ROUTE[outcome]


def artifact_fetch_uses_process_poll_response(workflow: dict, node_name: str) -> bool:
    params = node_by_name(workflow, node_name).get("parameters", {})
    url = str(params.get("url", ""))
    return (
        "Process Poll Response" in url
        and "final_artifact_id" in url
        and "final.artifact_id" not in url
    )


def submit_research_uses_brief_input(workflow: dict) -> bool:
    params = node_by_name(workflow, "Submit Research").get("parameters", {})
    body = str(params.get("jsonBody", ""))
    return "Parse Research Brief" in body and "brief" in body


def workflow_contains_stale_brief_payload(workflow: dict) -> bool:
    raw = json.dumps(workflow)
    return any(marker in raw for marker in STALE_BRIEF_MARKERS)


def terminal_branch_starts_with_failed_check(workflow: dict) -> bool:
    connections = workflow["connections"]["Is Terminal?"]["main"][0]
    return connections[0]["node"] == "Workflow Failed?"


def approved_branch_requires_final_artifact_id(workflow: dict) -> bool:
    params = node_by_name(workflow, "Approved Final Artifact?").get("parameters", {})
    raw = json.dumps(params)
    return "final_artifact_id" in raw and "isNotEmpty" in raw


def exported_workflow_by_name(exported: list[dict] | dict, name_fragment: str) -> dict:
    items = exported if isinstance(exported, list) else [exported]
    for item in items:
        if name_fragment in str(item.get("name", "")):
            return item
    raise KeyError(f"No exported workflow matching: {name_fragment}")
