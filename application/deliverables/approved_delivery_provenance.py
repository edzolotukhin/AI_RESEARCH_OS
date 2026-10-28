"""Typed identity of one exactly approved reader-facing delivery revision."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = (
    "report_id",
    "revision_number",
    "authority_digest",
    "presentation_digest",
    "review_id",
    "source_workflow_run_id",
    "report_workflow_run_id",
    "claim_set_digest",
    "coverage_contract_digest",
)


_ID_LIMITS = {
    "report_id": 36,
    "review_id": 64,
    "source_workflow_run_id": 64,
    "report_workflow_run_id": 64,
}


def _identity(value: object, field: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > _ID_LIMITS[field]):
        raise ValueError(f"invalid approved delivery {field}")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"invalid approved delivery {field}")
    return value


@dataclass(frozen=True)
class ApprovedDeliveryProvenance:
    report_id: str
    revision_number: int
    authority_digest: str
    presentation_digest: str
    review_id: str
    source_workflow_run_id: str
    report_workflow_run_id: str
    claim_set_digest: str
    coverage_contract_digest: str

    def __post_init__(self) -> None:
        for field in (
            "report_id",
            "review_id",
            "source_workflow_run_id",
            "report_workflow_run_id",
        ):
            _identity(getattr(self, field), field)
        if isinstance(self.revision_number, bool) or not isinstance(self.revision_number, int):
            raise ValueError("invalid approved delivery revision_number")
        if self.revision_number < 1:
            raise ValueError("invalid approved delivery revision_number")
        for field in (
            "authority_digest",
            "presentation_digest",
            "claim_set_digest",
            "coverage_contract_digest",
        ):
            _digest(getattr(self, field), field)

    def to_dict(self) -> dict[str, str | int]:
        return {field: getattr(self, field) for field in _FIELDS}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ApprovedDeliveryProvenance:
        if not isinstance(payload, Mapping) or set(payload) != set(_FIELDS):
            raise ValueError("invalid approved delivery provenance fields")
        return cls(**{field: payload[field] for field in _FIELDS})


def provenance_from_storage(
    *,
    report_id: str | None,
    revision_number: int | None,
    authority_digest: str | None,
    presentation_digest: str | None,
    review_id: str | None,
    source_workflow_run_id: str | None,
    report_workflow_run_id: str | None,
    claim_set_digest: str | None,
    coverage_contract_digest: str | None,
) -> ApprovedDeliveryProvenance | None:
    values = (
        revision_number,
        authority_digest,
        presentation_digest,
        review_id,
        source_workflow_run_id,
        claim_set_digest,
        coverage_contract_digest,
    )
    if all(value is None for value in values):
        return None
    if report_id is None or report_workflow_run_id is None or any(value is None for value in values):
        raise ValueError("partial approved delivery provenance")
    return ApprovedDeliveryProvenance(
        report_id=report_id,
        revision_number=revision_number,
        authority_digest=authority_digest,
        presentation_digest=presentation_digest,
        review_id=review_id,
        source_workflow_run_id=source_workflow_run_id,
        report_workflow_run_id=report_workflow_run_id,
        claim_set_digest=claim_set_digest,
        coverage_contract_digest=coverage_contract_digest,
    )


def validate_storage_binding(
    provenance: ApprovedDeliveryProvenance | None,
    *,
    report_id: str | None,
    report_workflow_run_id: str | None,
    revision_number: int | None = None,
    review_id: str | None = None,
    source_workflow_run_id: str | None = None,
    claim_set_digest: str | None = None,
    coverage_contract_digest: str | None = None,
) -> None:
    if provenance is None:
        return
    expected = {
        "report_id": report_id,
        "report_workflow_run_id": report_workflow_run_id,
        "revision_number": revision_number,
        "review_id": review_id,
        "source_workflow_run_id": source_workflow_run_id,
        "claim_set_digest": claim_set_digest,
        "coverage_contract_digest": coverage_contract_digest,
    }
    for field, value in expected.items():
        if value is not None and value != getattr(provenance, field):
            raise ValueError(f"approved delivery provenance {field} mismatch")
