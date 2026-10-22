"""Deterministic guard against report claims broader than their support."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight

_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_NUMBER = re.compile(
    r"(?P<prefix>[$€])?\s*(?P<value>\d+(?:[\s,.]\d+)*(?:[.,]\d+)?)\s*"
    r"(?P<scale>m|million|млн|млрд)?\s*"
    r"(?P<unit>%|percentage points?|відсот(?:ок|ки|ків)?|грн|uah|usd|руб|per\s+hour|на\s+годину)?",
    re.IGNORECASE,
)

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


def _numeric_facts(text: str) -> list[tuple[str, str, set[str]]]:
    facts: list[tuple[str, str, set[str]]] = []
    for match in _NUMBER.finditer(text):
        prefix = match.group("prefix") or ""
        scale = match.group("scale") or ""
        unit_value = match.group("unit") or ""
        if not prefix and not scale and not unit_value:
            continue
        value = re.sub(r"[\s,]", "", match.group("value")).replace(",", ".")
        unit = f"{prefix}{scale}{unit_value}".lower().replace(" ", "_")
        window = text[max(0, match.start() - 80):match.end() + 80]
        anchors = {
            token.lower()
            for token in _TOKEN.findall(window)
            if token[:1].isupper()
            or token.isdigit()
            or token.lower() in {"year", "року", "рік", "hour", "годину", "per", "на"}
        }
        facts.append((value, unit, anchors))
    return facts


def _numeric_scope_errors(content: str, support: str) -> tuple[str, ...]:
    supported = _numeric_facts(support)
    errors: list[str] = []
    for value, unit, context in _numeric_facts(content):
        matches = [item for item in supported if item[0] == value]
        if not matches:
            errors.append(f"unsupported numeric value: {value}")
            continue
        if not any(item[1] == unit for item in matches):
            errors.append(f"unsupported numeric unit: {value} {unit}")
            continue
        same_unit = [item for item in matches if item[1] == unit]
        if not any(context <= item[2] for item in same_unit):
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
) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """Return existing violations plus bounded, non-prose mismatch metadata."""
    support = _support_text(
        finding_ids,
        findings_by_id=findings_by_id,
        insights_by_id=insights_by_id,
        evidence_by_id=evidence_by_id,
    )
    claim_tokens = _tokens(content)
    support_tokens = _tokens(support)
    operators = claim_tokens & _BROADENING
    errors: list[str] = []
    mismatch: dict[str, Any] | None = None
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
    supported = _numeric_facts(support)
    for value, unit, context in _numeric_facts(content):
        matches = [item for item in supported if item[0] == value]
        if not matches:
            error = f"unsupported numeric value: {value}"
            errors.append(error)
            mismatch = {"rule": "unsupported_numeric_value", "candidate_value": value,
                        "supported_values": _bounded((item[0] for item in supported), _MAX_MISMATCH_VALUES)}
            continue
        if not any(item[1] == unit for item in matches):
            error = f"unsupported numeric unit: {value} {unit}"
            errors.append(error)
            mismatch = {"rule": "unsupported_numeric_unit", "candidate_value": value,
                        "candidate_unit": unit,
                        "supported_units": _bounded((item[1] for item in matches), _MAX_MISMATCH_VALUES)}
            continue
        same_unit = [item for item in matches if item[1] == unit]
        if not any(context <= item[2] for item in same_unit):
            errors.append(f"unsupported numeric scope: {value} {unit}")
            supported_context = {anchor for item in same_unit for anchor in item[2]}
            categories = []
            if any(anchor.isdigit() or anchor in {"year", "року", "рік"} for anchor in context | supported_context):
                categories.append("period")
            if any(anchor in {"per", "hour", "годину", "на"} for anchor in context | supported_context):
                categories.append("context")
            if not categories:
                categories.append("other")
            mismatch = {"rule": "unsupported_numeric_scope",
                        "anchor_category": categories[0],
                        "candidate_anchors": _bounded(context, _MAX_MISMATCH_ANCHORS),
                        "supported_anchors": _bounded(supported_context, _MAX_MISMATCH_ANCHORS)}
    return tuple(errors), mismatch


def validate_claim_scope(
    content: str,
    *,
    finding_ids: Iterable[str],
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
) -> tuple[str, ...]:
    """Return deterministic claim-scope violations; never broaden support."""
    errors, _ = validate_claim_scope_with_diagnostics(
        content,
        finding_ids=finding_ids,
        findings_by_id=findings_by_id,
        insights_by_id=insights_by_id,
        evidence_by_id=evidence_by_id,
    )
    return errors
