from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.one_way_statistics import QuantitativeAnalysisError


_T = TypeVar("_T")


SEMANTIC_EVIDENCE_VERSION = "P1_18_SEMANTIC_EVIDENCE_V1"


def semantic_evidence_context_projection(context) -> Mapping[str, Any]:
    """Return only canonical aggregate semantics already authorized by QH."""
    projection = {
        "context_id": context.context_id,
        "fingerprint": context.fingerprint,
        "result_id": context.result_id,
        "result_fingerprint": context.result_fingerprint,
        "variable_id": context.variable_id,
        "variable_fingerprint": context.variable_fingerprint,
        "variable_label": context.variable_label,
        "question_context": context.question_context,
        "category_code": canonical_scalar(context.category_code),
        "category_label": context.category_label,
        "exact_value": canonical_scalar(context.value),
        "display_value": context.display_value,
        "denominator": canonical_scalar(context.denominator),
        "filter_definition": context.filter_definition,
        "base_definition": context.base_definition,
        "weighting_status": context.weighting_status,
        "weight_set_fingerprint": context.weight_set_fingerprint,
        "provenance": context.provenance,
    }
    if context.population_description is not None:
        projection["population_description"] = context.population_description
    return projection


def validate_finding_semantic_context(
    finding,
    *,
    digest_provider: DeterministicDigestProvider,
) -> None:
    """Fail closed when P1-18 semantic authority is stale or internally altered."""
    context = finding.semantic_evidence_context
    if context is None:
        return
    if len(finding.statistical_result_refs) != 1:
        raise QuantitativeAnalysisError(
            "semantic evidence context requires one statistical result"
        )
    result_ref = finding.statistical_result_refs[0]
    claim = finding.claim
    if (
        not context.context_id
        or not context.fingerprint
        or not context.variable_label
        or not context.question_context
        or not context.category_label
        or not context.display_value
        or context.result_id != result_ref.result_id
        or context.result_fingerprint != result_ref.reproducibility_fingerprint
        or context.variable_id != claim.variable_id
        or context.category_code != claim.category_value
        or context.value != claim.value
        or context.display_value != claim.display_value
        or context.filter_definition != claim.filter_definition
        or context.base_definition != claim.base_definition
        or context.weighting_status != claim.weighting_status
        or context.weight_set_fingerprint != claim.weight_set_fingerprint
    ):
        raise QuantitativeAnalysisError(
            "semantic evidence context contradicts accepted Finding authority"
        )
    required_sources = {
        "STATISTICAL_RESULT", "VARIABLE_DEFINITION", "CODEBOOK_VERSION",
        "RC_ANALYSIS_PLAN", "RD_EXECUTION_MANIFEST",
    }
    if (
        {item[0] for item in context.provenance} != required_sources
        or any(len(item) != 3 or not all(item) for item in context.provenance)
    ):
        raise QuantitativeAnalysisError(
            "semantic evidence context provenance is incomplete"
        )
    payload = {
        "result": (context.result_id, context.result_fingerprint),
        "variable": (context.variable_id, context.variable_fingerprint),
        "variable_label": context.variable_label,
        "question_context": context.question_context,
        "category_code": canonical_scalar(context.category_code),
        "category_label": context.category_label,
        "filter": context.filter_definition,
        "base": context.base_definition,
        "denominator": canonical_scalar(context.denominator),
        "population_description": context.population_description,
        "value": canonical_scalar(context.value),
        "display_value": context.display_value,
        "weighting": (context.weighting_status, context.weight_set_fingerprint),
        "provenance": context.provenance,
        "version": SEMANTIC_EVIDENCE_VERSION,
    }
    if canonical_digest(payload, digest_provider=digest_provider) != context.fingerprint:
        raise QuantitativeAnalysisError(
            "semantic evidence context fingerprint mismatch"
        )


def finding_support_projection(finding) -> Mapping[str, Any]:
    """Return the bounded Finding authority shared by QJ and RF."""
    projection = {
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
    if finding.semantic_evidence_context is not None:
        projection["semantic_evidence_context"] = (
            semantic_evidence_context_projection(finding.semantic_evidence_context)
        )
    return projection


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
