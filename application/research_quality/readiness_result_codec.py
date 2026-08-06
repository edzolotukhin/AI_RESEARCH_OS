from __future__ import annotations

from typing import Any

from application.research_quality.research_loop_state import SHARED_LOOP_STATE_KEY
from application.research_quality.research_readiness_service import SHARED_STATE_KEY


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
