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

POLL_STATE_FIELDS = (
    "run_id",
    "project_id",
    "api_url",
    "correlation_id",
    "idempotency_key",
    "poll_attempt",
    "max_poll_attempts",
    "poll_interval_seconds",
)

POLL_RESPONSE_FIELDS = (
    "status",
    "is_terminal",
    "final_review_verdict",
    "final_artifact_available",
    "final_artifact_id",
)

FRAGILE_POLL_NODE_REFS = (
    "$('Continue Poll Loop')",
    "$('Prepare Poll Loop')",
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


def merge_poll_state(loop_state: dict, poll_response: dict) -> dict:
    """Mirror Merge Poll State combineByPosition output."""
    merged = dict(loop_state)
    merged.update(poll_response)
    return merged


def process_poll_response(merged_item: dict) -> dict:
    """Mirror Process Poll Response Code node logic."""
    item = merged_item
    return {
        "run_id": item["run_id"],
        "project_id": item["project_id"],
        "api_url": item["api_url"],
        "correlation_id": item["correlation_id"],
        "idempotency_key": item["idempotency_key"],
        "poll_attempt": int(item.get("poll_attempt") or 0) + 1,
        "max_poll_attempts": int(item["max_poll_attempts"]),
        "poll_interval_seconds": item["poll_interval_seconds"],
        "status": item["status"],
        "is_terminal": bool(item["is_terminal"]),
        "final_review_verdict": item.get("final_review_verdict"),
        "final_artifact_available": bool(item.get("final_artifact_available")),
        "final_artifact_id": item.get("final_artifact_id"),
    }


def continue_poll_loop(poll_state: dict) -> dict:
    """Mirror Continue Poll Loop Code node — preserves loop state for next iteration."""
    return {
        "run_id": poll_state["run_id"],
        "poll_attempt": poll_state["poll_attempt"],
        "max_poll_attempts": poll_state["max_poll_attempts"],
        "api_url": poll_state["api_url"],
        "project_id": poll_state["project_id"],
        "correlation_id": poll_state["correlation_id"],
        "idempotency_key": poll_state["idempotency_key"],
        "poll_interval_seconds": poll_state["poll_interval_seconds"],
    }


def is_terminal_branch(poll: dict) -> str:
    """Return 'terminal' or 'continue' mirroring Is Terminal? IF node."""
    return "terminal" if poll.get("is_terminal") else "continue"


def max_poll_attempts_branch(poll: dict) -> str:
    """Return 'timeout' or 'wait' mirroring Max Poll Attempts? IF node."""
    attempt = int(poll.get("poll_attempt", 0))
    maximum = int(poll.get("max_poll_attempts", 0))
    return "timeout" if attempt >= maximum else "wait"


def process_poll_response_code(workflow: dict) -> str:
    return node_by_name(workflow, "Process Poll Response")["parameters"]["jsCode"]


def process_poll_response_has_no_node_refs(workflow: dict) -> bool:
    code = process_poll_response_code(workflow)
    return not any(ref in code for ref in FRAGILE_POLL_NODE_REFS)


def poll_loop_uses_merge_node(workflow: dict) -> bool:
    node = node_by_name(workflow, "Merge Poll State")
    return node["type"] == "n8n-nodes-base.merge"


def is_terminal_if_condition(workflow: dict) -> dict | None:
    params = node_by_name(workflow, "Is Terminal?").get("parameters", {})
    conditions = params.get("conditions", {})
    for item in conditions.get("conditions", []):
        left = str(item.get("leftValue", ""))
        if "is_terminal" in left:
            return item
    return None


def is_terminal_condition_survives_export(workflow: dict) -> bool:
    node = node_by_name(workflow, "Is Terminal?")
    if node.get("typeVersion", 0) < 2.2:
        return False
    condition = is_terminal_if_condition(workflow)
    if not condition:
        return False
    operator = condition.get("operator", {})
    return (
        operator.get("type") == "boolean"
        and operator.get("operation") == "equals"
        and condition.get("rightValue") is True
        and "is_terminal" in str(condition.get("leftValue", ""))
    )


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


def artifact_fetch_uses_item_json(workflow: dict, node_name: str) -> bool:
    params = node_by_name(workflow, node_name).get("parameters", {})
    url = str(params.get("url", ""))
    return (
        "$json.api_url" in url
        and "$json.final_artifact_id" in url
        and "final.artifact_id" not in url
        and "Process Poll Response" not in url
    )


def artifact_fetch_uses_process_poll_response(workflow: dict, node_name: str) -> bool:
    """Deprecated alias — artifact fetch now uses $json from IF branch passthrough."""
    return artifact_fetch_uses_item_json(workflow, node_name)


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
    return "final_artifact_id" in raw and "notEmpty" in raw


def exported_workflow_by_name(exported: list[dict] | dict, name_fragment: str) -> dict:
    items = exported if isinstance(exported, list) else [exported]
    for item in items:
        if name_fragment in str(item.get("name", "")):
            return item
    raise KeyError(f"No exported workflow matching: {name_fragment}")
