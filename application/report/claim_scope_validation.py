"""Deterministic guard against report claims broader than their support."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from application.research_scope.authoritative_scope import (
    SCOPE_VERSION,
    numeric_facts,
    sanitize_scope,
    scope_for_finding,
)

_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_NUMBER = re.compile(
    r"(?P<prefix>[$€])?\s*(?P<value>\d+(?:[\s,.]\d+)*(?:[.,]\d+)?)\s*"
    r"(?P<scale>m|million|млн|млрд)?\s*"
    r"(?P<unit>%|percentage points?|відсот(?:ок|ки|ків)?|грн|uah|usd|руб|per\s+hour|на\s+годину)?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DATE = re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}(?!\d)")

# These are scope-changing operators, not domain vocabulary.  A claim using
# one of them must be grounded by the authoritative support itself.
_BROADENING = frozenset(
    {
        "all", "every", "entire", "overall", "across", "generally", "mostly",
        "predominantly", "usually", "most", "every", "each", "all", "always",
        "never", "none", "caused", "causes", "resulted", "because", "due", "всі",
        "усі", "весь", "кожен", "кожна", "кожне", "кожні", "жоден", "більшість",
        "загалом", "переважно", "здебільшого", "завжди", "ніколи", "спричинило",
        "спричиняє", "призвело", "через",
    }
)
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "for", "with", "from",
        "that", "this", "was", "were", "is", "are", "as", "on", "by", "та", "і",
        "або", "у", "в", "з", "до", "для", "що", "це", "є", "як", "на", "по",
    }
)
_MAX_MISMATCH_TOKENS = 8
_MAX_MISMATCH_VALUES = 8
_MAX_MISMATCH_ANCHORS = 8


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN.findall(text)
        if token.lower() not in _STOP and len(token) > 2
    }


def _support_text(
    finding_ids: Iterable[str],
    *,
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
) -> str:
    evidence_ids: set[str] = set()
    parts: list[str] = []
    for finding_id in finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            continue
        parts.extend((finding.statement, finding.rationale))
        evidence_ids.update(finding.evidence_refs)
    for insight in insights_by_id.values():
        if any(ref in findings_by_id for ref in insight.finding_refs):
            parts.extend((insight.statement, insight.implication))
            for finding_id in insight.finding_refs:
                finding = findings_by_id.get(finding_id)
                if finding is not None:
                    evidence_ids.update(finding.evidence_refs)
    for evidence_id in evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is not None:
            parts.extend((evidence.statement, evidence.source_excerpt))
    return " ".join(parts)


def _finding_support_scope(
    finding_ids: Iterable[str], *, findings_by_id: dict[str, Finding],
    evidence_by_id: dict[str, Evidence],
) -> dict[str, Any]:
    scopes: list[dict[str, Any]] = []
    for finding_id in finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            continue
        scopes.append(scope_for_finding(finding, evidence_by_id))
    return sanitize_scope({
        "version": SCOPE_VERSION,
        "geography": [value for scope in scopes for value in scope["geography"]],
        "geography_anchors": [
            value for scope in scopes for value in scope["geography_anchors"]
        ],
        "periods": [value for scope in scopes for value in scope["periods"]],
        "metrics": [value for scope in scopes for value in scope["metrics"]],
        "population_dimensions": [
            value for scope in scopes for value in scope["population_dimensions"]
        ],
        "numeric_facts": [value for scope in scopes for value in scope["numeric_facts"]],
        "source": "finding_or_authoritative_evidence",
    })


def _numeric_scope_errors(content: str, support_scope: dict[str, Any]) -> tuple[str, ...]:
    supported = support_scope["numeric_facts"]
    errors: list[str] = []
    for fact in numeric_facts(content):
        value, unit = fact["value"], fact["unit"]
        periods = set(fact["periods"])
        matches = [item for item in supported if item["value"] == value]
        if not matches:
            errors.append(f"unsupported numeric value: {value}")
            continue
        if not any(item["unit"] == unit for item in matches):
            errors.append(f"unsupported numeric unit: {value} {unit}")
            continue
        same_unit = [item for item in matches if item["unit"] == unit]
        if periods and not any(periods <= set(item["periods"]) for item in same_unit):
            errors.append(f"unsupported numeric scope: {value} {unit}")
    return tuple(errors)


def _bounded(values: Iterable[str], limit: int) -> list[str]:
    return sorted({value for value in values if value})[:limit]


def validate_claim_scope_with_diagnostics(
    content: str,
    *,
    finding_ids: Iterable[str],
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
    claim_scope: dict[str, Any] | None = None,
) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """Return existing violations plus bounded, non-prose mismatch metadata."""
    support = _support_text(
        finding_ids,
        findings_by_id=findings_by_id,
        insights_by_id=insights_by_id,
        evidence_by_id=evidence_by_id,
    )
    support_scope = _finding_support_scope(
        finding_ids, findings_by_id=findings_by_id, evidence_by_id=evidence_by_id,
    )
    claim_tokens = _tokens(content)
    support_tokens = _tokens(support)
    operators = claim_tokens & _BROADENING
    errors: list[str] = []
    rejections: list[dict[str, Any]] = []

    def reject(error: str, mismatch: dict[str, Any]) -> None:
        if error not in errors:
            errors.append(error)
            rejections.append(mismatch)

    candidate_scope: dict[str, Any] | None = None
    if claim_scope is not None:
        candidate_scope = sanitize_scope(claim_scope)
        for field, dimension in (
            ("periods", "period"), ("geography", "geography"),
            ("metrics", "metric"),
            ("population_dimensions", "population_dimension"),
        ):
            candidate_values = set(candidate_scope[field])
            supported_values = set(support_scope[field])
            unsupported_values = candidate_values - supported_values
            if unsupported_values:
                reject(
                    f"Report claim uses unsupported {dimension} scope",
                    {
                        "rule": "broadening_scope", "dimension": dimension,
                        "candidate_anchors": _bounded(
                            candidate_values, _MAX_MISMATCH_TOKENS,
                        ),
                        "supported_anchors": _bounded(
                            supported_values, _MAX_MISMATCH_TOKENS,
                        ),
                        "rejected_tokens": _bounded(
                            unsupported_values, _MAX_MISMATCH_TOKENS,
                        ),
                    },
                )
    if operators:
        unsupported = claim_tokens - support_tokens - _BROADENING
        if unsupported:
            reject(
                "Report claim broadens the supported scope: "
                f"operators={sorted(operators)} unsupported_scope={sorted(unsupported)}",
                {
                    "rule": "broadening_scope",
                    "dimension": "generality",
                    "operators": _bounded(operators, _MAX_MISMATCH_TOKENS),
                    "rejected_tokens": _bounded(unsupported, _MAX_MISMATCH_TOKENS),
                },
            )
    supported = support_scope["numeric_facts"]
    for fact in numeric_facts(content):
        value, unit = fact["value"], fact["unit"]
        periods = set(fact["periods"])
        matches = [item for item in supported if item["value"] == value]
        if not matches:
            reject(
                f"unsupported numeric value: {value}",
                {"rule": "unsupported_numeric_value", "dimension": "numeric_value",
                 "candidate_value": value,
                 "supported_values": _bounded(
                     (item["value"] for item in supported), _MAX_MISMATCH_VALUES,
                 )},
            )
            continue
        if not any(item["unit"] == unit for item in matches):
            reject(
                f"unsupported numeric unit: {value} {unit}",
                {"rule": "unsupported_numeric_unit", "dimension": "unit",
                 "candidate_value": value, "candidate_unit": unit,
                 "supported_units": _bounded(
                     (item["unit"] for item in matches), _MAX_MISMATCH_VALUES,
                 )},
            )
            continue
        same_unit = [item for item in matches if item["unit"] == unit]
        if periods and not any(periods <= set(item["periods"]) for item in same_unit):
            supported_context = {anchor for item in same_unit for anchor in item["periods"]}
            reject(
                f"unsupported numeric scope: {value} {unit}",
                {"rule": "unsupported_numeric_scope", "dimension": "period",
                 "anchor_category": "period",
                 "candidate_anchors": _bounded(periods, _MAX_MISMATCH_ANCHORS),
                 "supported_anchors": _bounded(
                     supported_context, _MAX_MISMATCH_ANCHORS,
                 )},
            )

    if candidate_scope is not None:
        for fact in candidate_scope["numeric_facts"]:
            value, unit = fact["value"], fact["unit"]
            matches = [
                item for item in supported
                if item["value"] == value and item["unit"] == unit
            ]
            if not matches:
                continue  # value/unit rejection is already handled above or by content.
            for field, dimension in (
                ("periods", "period"), ("geography", "geography"),
                ("metrics", "metric"),
                ("population_dimensions", "population_dimension"),
            ):
                candidate_values = set(fact[field])
                if not candidate_values:
                    continue
                if any(candidate_values <= set(item[field]) for item in matches):
                    continue
                supported_values = {value for item in matches for value in item[field]}
                reject(
                    f"unsupported numeric scope: {value} {unit} {dimension}",
                    {"rule": "unsupported_numeric_scope", "dimension": dimension,
                     "anchor_category": dimension,
                     "candidate_anchors": _bounded(
                         candidate_values, _MAX_MISMATCH_ANCHORS,
                     ),
                     "supported_anchors": _bounded(
                         supported_values, _MAX_MISMATCH_ANCHORS,
                     )},
                )

    if not rejections:
        return tuple(errors), None
    primary = dict(rejections[0])
    primary["rejections"] = rejections[:_MAX_MISMATCH_VALUES]
    return tuple(errors), primary


def validate_claim_scope(
    content: str,
    *,
    finding_ids: Iterable[str],
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
    claim_scope: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return deterministic claim-scope violations; never broaden support."""
    errors, _ = validate_claim_scope_with_diagnostics(
        content,
        finding_ids=finding_ids,
        findings_by_id=findings_by_id,
        insights_by_id=insights_by_id,
        evidence_by_id=evidence_by_id,
        claim_scope=claim_scope,
    )
    return errors
