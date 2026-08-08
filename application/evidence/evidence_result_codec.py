from __future__ import annotations

from typing import Any

from application.evidence.evidence_failure_diagnostics_persistence import (
    EVIDENCE_EXTRACTION_SHARED_KEY,
)


def extract_evidence_extraction(
    task_results: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the latest evidence_extraction payload from durable task snapshots."""
    if not task_results:
        return None

    for snapshot in task_results.values():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        if not isinstance(shared_state, dict):
            continue
        payload = shared_state.get(EVIDENCE_EXTRACTION_SHARED_KEY)
        if isinstance(payload, dict):
            return payload
    return None
