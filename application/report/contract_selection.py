"""Stable Desk report-contract selection and durable pinning."""

from __future__ import annotations

from typing import Any, Mapping

H2_REPORT_CONTRACT = "desk_report_claim_v1"
H3_REPORT_CONTRACT = "desk_h3_structural_claim_v1"
LEGACY_EDITORIAL_CONTRACT = "desk_editorial_v1"
DESK_REPORT_CONTRACT_PIN = "_desk_report_contract_v1"
SUPPORTED_DESK_REPORT_CONTRACTS = frozenset({
    H2_REPORT_CONTRACT,
    H3_REPORT_CONTRACT,
    LEGACY_EDITORIAL_CONTRACT,
})


def validate_desk_report_contract(value: str) -> str:
    value = str(value or "").strip()
    if value not in SUPPORTED_DESK_REPORT_CONTRACTS:
        raise ValueError(f"Unsupported DESK_REPORT_CONTRACT_VERSION: {value!r}")
    return value


def pin_desk_report_contract(
    task_results: Mapping[str, Any] | None,
    contract: str,
) -> dict[str, Any]:
    """Return initial durable results with an immutable contract selection."""
    selected = validate_desk_report_contract(contract)
    if selected not in {H2_REPORT_CONTRACT, H3_REPORT_CONTRACT}:
        raise ValueError(
            "Only complete Desk execution contracts may be pinned: "
            f"{selected!r}"
        )
    results = dict(task_results or {})
    existing = results.get(DESK_REPORT_CONTRACT_PIN)
    if existing is not None and existing != selected:
        raise ValueError("Desk report contract is already pinned")
    results[DESK_REPORT_CONTRACT_PIN] = selected
    return results


def resolve_pinned_desk_report_contract(
    task_results: Mapping[str, Any] | None,
    *,
    fallback: str | None = None,
) -> str:
    results = task_results or {}
    pinned = results.get(DESK_REPORT_CONTRACT_PIN)
    if not isinstance(pinned, str):
        if fallback is None:
            raise ValueError("Desk report contract is not durably pinned")
        return validate_desk_report_contract(fallback)
    return validate_desk_report_contract(pinned)
