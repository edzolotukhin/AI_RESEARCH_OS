from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from application.quantitative.one_way_statistics import QuantitativeAnalysisError


_T = TypeVar("_T")


def finding_support_projection(finding) -> Mapping[str, Any]:
    """Return the bounded Finding authority shared by QJ and RF."""
    return {
        "finding_id": finding.finding_id,
        "support_validation_fingerprint": finding.support_validation_fingerprint,
        "analytical_context_fingerprint": finding.analytical_context_fingerprint,
        "claim_type": finding.claim.claim_type.value,
        "finding_text": finding.text,
        "display_value": finding.claim.display_value,
        "direction": finding.claim.direction,
        "filter_definition": finding.claim.filter_definition,
        "base_definition": finding.claim.base_definition,
        "weighting_status": finding.claim.weighting_status,
        "weight_set_fingerprint": finding.claim.weight_set_fingerprint,
    }


def canonical_finding_support_bundle(
    items: Sequence[_T],
    *,
    projection: Callable[[_T], Mapping[str, Any]] = finding_support_projection,
) -> tuple[Mapping[str, Any], ...]:
    """Canonicalize the order-insensitive, duplicate-free QJ Finding bundle."""
    projected = tuple(dict(projection(item)) for item in items)
    finding_ids = tuple(item.get("finding_id") for item in projected)
    if any(not isinstance(item, str) or not item for item in finding_ids):
        raise QuantitativeAnalysisError("Insight input contains an invalid Finding ID")
    if len(finding_ids) != len(set(finding_ids)):
        raise QuantitativeAnalysisError("Insight input contains duplicate Finding IDs")
    return tuple(sorted(projected, key=lambda item: item["finding_id"]))
