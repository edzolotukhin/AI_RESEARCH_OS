from __future__ import annotations

from typing import Any

from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.research_readiness_service import SHARED_STATE_KEY

_RESEARCH_OUTCOME_KEY = "research_product_outcome"
_VALID_RESEARCH_OUTCOMES = {"COMPLETED", "PARTIAL", "INSUFFICIENT", "FAILED"}


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

    candidates: list[dict[str, Any]] = []

    def add_candidate(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Malformed research_product_outcome payload")
        outcome = payload.get("outcome")
        if not isinstance(outcome, str) or outcome not in _VALID_RESEARCH_OUTCOMES:
            raise ValueError("Invalid research_product_outcome value")
        candidates.append(payload)

    legacy = task_results.get(_RESEARCH_OUTCOME_KEY)
    if legacy is not None:
        add_candidate(legacy)

    for snapshot in task_results.values():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        if not isinstance(shared_state, dict):
            continue
        if _RESEARCH_OUTCOME_KEY in shared_state:
            add_candidate(shared_state[_RESEARCH_OUTCOME_KEY])
        readiness = shared_state.get("research_readiness")
        if isinstance(readiness, dict) and _RESEARCH_OUTCOME_KEY in readiness:
            add_candidate(readiness[_RESEARCH_OUTCOME_KEY])

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
