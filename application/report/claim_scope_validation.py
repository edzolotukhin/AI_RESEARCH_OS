"""Deterministic guard against report claims broader than their support."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from application.research_scope.authoritative_scope import (
    SCOPE_KEY,
    SCOPE_VERSION,
    combine_evidence_scopes,
    numeric_facts,
    sanitize_scope,
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
_NON_GEOGRAPHY_PROPER = frozenset(
    {"in", "the", "during", "for", "from", "year", "index", "share", "total",
     "за", "на", "року", "рік", "та", "сукупно", "слабша", "індекс", "це",
     "частка", "менша", "так", "одночасно", "очікування"}
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


def _proper_anchors(text: str) -> set[str]:
    return {
        token.casefold() for token in _TOKEN.findall(text)
        if token[:1].isupper() and token.casefold() not in _NON_GEOGRAPHY_PROPER
        and not _YEAR.fullmatch(token)
    }


def _finding_support_scope(
    finding_ids: Iterable[str], *, findings_by_id: dict[str, Finding],
    evidence_by_id: dict[str, Evidence],
) -> dict[str, Any]:
    evidence: list[Evidence] = []
    scopes: list[dict[str, Any]] = []
    for finding_id in finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            continue
        raw = finding.metadata.get(SCOPE_KEY)
        if isinstance(raw, dict) and raw.get("version") == SCOPE_VERSION:
            scopes.append(sanitize_scope(raw))
        else:
            # Historical fallback is restricted to cited authoritative Evidence.
            evidence.extend(
                evidence_by_id[ref] for ref in finding.evidence_refs if ref in evidence_by_id
            )
    if evidence:
        scopes.append(combine_evidence_scopes(evidence))
    return sanitize_scope({
        "version": SCOPE_VERSION,
        "geography": [value for scope in scopes for value in scope["geography"]],
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
    mismatch: dict[str, Any] | None = None
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
                errors.append(f"Report claim uses unsupported {dimension} scope")
                mismatch = {
                    "rule": "broadening_scope", "dimension": dimension,
                    "rejected_tokens": _bounded(
                        unsupported_values, _MAX_MISMATCH_TOKENS,
                    ),
                }
    if operators:
        unsupported = claim_tokens - support_tokens - _BROADENING
        if unsupported:
            errors.append(
                "Report claim broadens the supported scope: "
                f"operators={sorted(operators)} unsupported_scope={sorted(unsupported)}",
            )
            mismatch = {
                "rule": "broadening_scope",
                "operators": _bounded(operators, _MAX_MISMATCH_TOKENS),
                "rejected_tokens": _bounded(unsupported, _MAX_MISMATCH_TOKENS),
            }
    supported = support_scope["numeric_facts"]
    supported_geography = set(support_scope["geography"])
    supported_geo_tokens = {
        token for value in supported_geography for token in _tokens(value)
    } or _proper_anchors(support)
    for fact in numeric_facts(content):
        value, unit = fact["value"], fact["unit"]
        periods = set(fact["periods"])
        matches = [item for item in supported if item["value"] == value]
        if not matches:
            error = f"unsupported numeric value: {value}"
            errors.append(error)
            mismatch = {"rule": "unsupported_numeric_value", "candidate_value": value,
                        "supported_values": _bounded((item["value"] for item in supported), _MAX_MISMATCH_VALUES)}
            continue
        if not any(item["unit"] == unit for item in matches):
            error = f"unsupported numeric unit: {value} {unit}"
            errors.append(error)
            mismatch = {"rule": "unsupported_numeric_unit", "candidate_value": value,
                        "candidate_unit": unit,
                        "supported_units": _bounded((item["unit"] for item in matches), _MAX_MISMATCH_VALUES)}
            continue
        same_unit = [item for item in matches if item["unit"] == unit]
        if periods and not any(periods <= set(item["periods"]) for item in same_unit):
            errors.append(f"unsupported numeric scope: {value} {unit}")
            supported_context = {anchor for item in same_unit for anchor in item["periods"]}
            mismatch = {"rule": "unsupported_numeric_scope",
                        "anchor_category": "period",
                        "candidate_anchors": _bounded(periods, _MAX_MISMATCH_ANCHORS),
                        "supported_anchors": _bounded(supported_context, _MAX_MISMATCH_ANCHORS)}
            continue
        # Geography is a distinct comparison and is never mixed into period
        # anchors. Historical fallback uses proper-name tokens only for the
        # numeric claim being checked.
        claimed_geo_tokens = _proper_anchors(content)
        unsupported_geo = claimed_geo_tokens - supported_geo_tokens
        if supported_geo_tokens and unsupported_geo:
            errors.append("Report claim uses unsupported geography")
            mismatch = {
                "rule": "broadening_scope", "dimension": "geography",
                "rejected_tokens": _bounded(unsupported_geo, _MAX_MISMATCH_TOKENS),
            }
    return tuple(errors), mismatch


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
