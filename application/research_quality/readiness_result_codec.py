from __future__ import annotations

from typing import Any

from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from application.research_quality.workflow_task_ids import (
    DOWNSTREAM_TASK_DEFINITION_IDS,
    TASK_ASSESS_RESEARCH_READINESS,
)

_RESEARCH_OUTCOME_KEY = "research_product_outcome"
_VALID_RESEARCH_OUTCOMES = {"COMPLETED", "PARTIAL", "INSUFFICIENT", "FAILED"}
_REPORT_TASK_ID = "task-write-report"
_ANALYSIS_TASK_ID = "task-analyze"


def extract_research_readiness(
    task_results: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the latest research_readiness payload from durable task snapshots."""
    if not task_results:
        return None

    for snapshot in task_results.values():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        if not isinstance(shared_state, dict):
            continue
        payload = shared_state.get(SHARED_STATE_KEY)
        if isinstance(payload, dict):
            return payload
    return None


def extract_research_product_outcome(
    task_results: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Extract the authoritative outcome from durable task snapshots.

    Task results are keyed by task id; shared state is nested in each snapshot.
    The legacy top-level shape is accepted for backward compatibility. Conflicting
    non-failure outcomes are rejected rather than selected arbitrarily. FAILED is
    fail-closed and takes precedence over a later non-failure snapshot.
    """
    if not task_results:
        return None

    authoritative: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []

    def add_candidate(payload: Any, target: list[dict[str, Any]]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Malformed research_product_outcome payload")
        outcome = payload.get("outcome")
        if not isinstance(outcome, str) or outcome not in _VALID_RESEARCH_OUTCOMES:
            raise ValueError("Invalid research_product_outcome value")
        target.append(payload)

    legacy_payload = task_results.get(_RESEARCH_OUTCOME_KEY)

    for task_key, snapshot in task_results.items():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        if not isinstance(shared_state, dict):
            continue
        definition_id = snapshot.get("definition_id")
        definition = definition_id or task_key
        is_report_stage = definition == _REPORT_TASK_ID
        is_provisional_stage = definition in {
            TASK_ASSESS_RESEARCH_READINESS,
            _ANALYSIS_TASK_ID,
        }
        is_known_downstream = (
            definition in DOWNSTREAM_TASK_DEFINITION_IDS
            and not is_provisional_stage
        )
        if _RESEARCH_OUTCOME_KEY in shared_state:
            if is_report_stage or is_known_downstream:
                add_candidate(shared_state[_RESEARCH_OUTCOME_KEY], authoritative)
            elif not is_provisional_stage:
                raise ValueError(
                    "Unclassified task snapshot contains research_product_outcome"
                )
            else:
                add_candidate(shared_state[_RESEARCH_OUTCOME_KEY], provisional)
        readiness = shared_state.get("research_readiness")
        if isinstance(readiness, dict) and _RESEARCH_OUTCOME_KEY in readiness:
            add_candidate(readiness[_RESEARCH_OUTCOME_KEY], provisional)

    if not authoritative and not provisional and legacy_payload is not None:
        add_candidate(legacy_payload, legacy)
    candidates = authoritative or provisional or legacy
    if not candidates:
        return None
    outcomes = {item["outcome"] for item in candidates}
    if "FAILED" in outcomes:
        failures = [item for item in candidates if item["outcome"] == "FAILED"]
        if any(item != failures[0] for item in failures[1:]):
            raise ValueError("Conflicting FAILED research_product_outcome payloads")
        return failures[0]
    if len(outcomes) != 1:
        raise ValueError("Conflicting research_product_outcome payloads")
    if any(item != candidates[0] for item in candidates[1:]):
        raise ValueError("Ambiguous research_product_outcome metadata")
    return candidates[0]


def extract_research_loop_state(
    task_results: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return persisted research loop state from durable task snapshots."""
    if not task_results:
        return None

    for snapshot in task_results.values():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        if not isinstance(shared_state, dict):
            continue
        payload = shared_state.get(SHARED_LOOP_STATE_KEY)
        if isinstance(payload, dict):
            return payload
    return None
