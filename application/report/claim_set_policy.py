"""Fail-closed contract policy for persisted ReportClaim sets."""

from __future__ import annotations

from collections.abc import Sequence

from domain.reports.report_claim import (
    H3_REPORT_CLAIM_VERSION,
    REPORT_CLAIM_VERSION,
    REPORT_CLAIM_V2_VERSION,
    ReportClaim,
)


ALLOWED_CLAIM_SET_VERSIONS = frozenset({
    REPORT_CLAIM_VERSION,
    REPORT_CLAIM_V2_VERSION,
    H3_REPORT_CLAIM_VERSION,
})


class ClaimSetContractError(ValueError):
    """A persisted claim set is empty, unsupported or mixed-version."""


def validate_homogeneous_claim_set(
    claims: Sequence[ReportClaim], *, allow_empty: bool = True,
) -> str | None:
    """Validate one homogeneous contract family; empty sets have no status."""
    if not claims:
        if allow_empty:
            return None
        raise ClaimSetContractError("ReportClaim claim set must not be empty")
    versions = {claim.contract_version for claim in claims}
    if not versions <= ALLOWED_CLAIM_SET_VERSIONS:
        raise ClaimSetContractError("ReportClaim claim set contains unsupported contract version")
    if len(versions) != 1:
        raise ClaimSetContractError("ReportClaim claim set contains mixed contract versions")
    return next(iter(versions))


def validate_homogeneous_append(
    existing_versions: Sequence[str], claims: Sequence[ReportClaim],
) -> str | None:
    """Validate a batch together with versions already in the same membership."""
    incoming_version = validate_homogeneous_claim_set(claims)
    versions = set(existing_versions)
    if not versions:
        return incoming_version
    if not versions <= ALLOWED_CLAIM_SET_VERSIONS:
        raise ClaimSetContractError("existing ReportClaim membership has unsupported contract version")
    if incoming_version is not None:
        versions.add(incoming_version)
    if len(versions) != 1:
        raise ClaimSetContractError("ReportClaim append changes the contract version")
    return next(iter(versions))
