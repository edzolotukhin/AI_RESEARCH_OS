"""Deterministic guard against report claims broader than their support."""

from __future__ import annotations

import re
from collections.abc import Iterable

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight

_TOKEN = re.compile(r"[\w]+", re.UNICODE)

# These are scope-changing operators, not domain vocabulary.  A claim using
# one of them must be grounded by the authoritative support itself.
_BROADENING = frozenset(
    {
        "all", "every", "entire", "overall", "across", "generally", "mostly",
        "predominantly", "usually", "most", "always", "never", "caused", "causes",
        "resulted", "because", "due", "всі", "весь", "більшість", "загалом",
        "переважно", "здебільшого", "завжди", "ніколи", "спричинило", "спричиняє",
        "призвело", "через",
    }
)
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "for", "with", "from",
        "that", "this", "was", "were", "is", "are", "as", "on", "by", "та", "і",
        "або", "у", "в", "з", "до", "для", "що", "це", "є", "як", "на", "по",
    }
)


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


def validate_claim_scope(
    content: str,
    *,
    finding_ids: Iterable[str],
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
) -> tuple[str, ...]:
    """Return deterministic claim-scope violations; never broaden support."""
    claim_tokens = _tokens(content)
    support_tokens = _tokens(
        _support_text(
            finding_ids,
            findings_by_id=findings_by_id,
            insights_by_id=insights_by_id,
            evidence_by_id=evidence_by_id,
        ),
    )
    operators = claim_tokens & _BROADENING
    if not operators:
        return ()
    unsupported_scope_tokens = claim_tokens - support_tokens - _BROADENING
    if not unsupported_scope_tokens:
        return ()
    return (
        "Report claim broadens the supported scope: "
        f"operators={sorted(operators)} unsupported_scope={sorted(unsupported_scope_tokens)}",
    )
