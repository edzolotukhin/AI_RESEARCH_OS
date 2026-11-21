from __future__ import annotations

from typing import Any

from application.evidence.evidence_failure_diagnostics_persistence import (
    EVIDENCE_EXTRACTION_SHARED_KEY,
)

MAX_CANDIDATE_DIAGNOSTIC_RECORDS = 500


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


def extract_candidate_rejection_diagnostics(
    task_results: dict[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Merge copied task snapshots into one bounded deterministic projection."""
    if not task_results:
        return ()
    records: dict[tuple[Any, ...], dict[str, Any]] = {}
    for snapshot in task_results.values():
        if not isinstance(snapshot, dict):
            continue
        shared_state = snapshot.get("shared_state")
        payload = shared_state.get(EVIDENCE_EXTRACTION_SHARED_KEY) if isinstance(shared_state, dict) else None
        diagnostics = payload.get("diagnostics") if isinstance(payload, dict) else None
        raw_records = diagnostics.get("candidate_rejection_diagnostics") if isinstance(diagnostics, dict) else None
        if not isinstance(raw_records, list):
            continue
        for raw in raw_records[:MAX_CANDIDATE_DIAGNOSTIC_RECORDS]:
            if not isinstance(raw, dict):
                continue
            fields = (
                "workflow_run_id", "source_id", "information_need_id", "operation_id",
                "candidate_index", "validation_phase", "rejection_code", "contract_version",
            )
            if any(field not in raw for field in fields):
                continue
            if not all(isinstance(raw[field], str) for field in fields if field != "candidate_index"):
                continue
            if not isinstance(raw["candidate_index"], int) or raw["candidate_index"] < 0:
                continue
            record = {field: raw[field] for field in fields}
            key = tuple(record[field] for field in fields)
            records[key] = record
            if len(records) >= MAX_CANDIDATE_DIAGNOSTIC_RECORDS:
                break
    ordered = sorted(records.values(), key=lambda item: tuple(item[field] for field in (
        "workflow_run_id", "source_id", "information_need_id", "operation_id",
        "candidate_index", "validation_phase", "rejection_code", "contract_version",
    )))
    return tuple(ordered[:MAX_CANDIDATE_DIAGNOSTIC_RECORDS])
