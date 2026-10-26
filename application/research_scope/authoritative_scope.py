"""Build bounded authoritative scope from validated Desk artifacts.

The contract deliberately keeps scope dimensions separate.  It is stored in
existing versioned metadata, so historical rows remain readable without a DB
migration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from application.evidence.semantic_assignment import semantic_assignment
from application.research_scope.numeric_normalization import (
    normalize_numeric_unit,
    normalize_numeric_value,
)
from domain.evidence.evidence import Evidence

SCOPE_KEY = "authoritative_scope"
SCOPE_VERSION = "desk_authoritative_scope_v1"
MAX_SCOPE_VALUES = 32
MAX_NUMERIC_FACTS = 64
GEOGRAPHY_LEVELS = frozenset({"country", "subnational", "unspecified"})

_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DATE = re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}(?!\d)")
_QUARTER = re.compile(r"\b(?:Q[1-4]\s+(?:19|20)\d{2}|(?:19|20)\d{2}\s+Q[1-4])\b", re.I)
_NUMBER = re.compile(
    r"(?P<prefix>[$€])?\s*(?P<value>\d+(?:[\s,.]\d+)*(?:[.,]\d+)?)\s*"
    r"(?P<scale>m|million|млн|млрд)?\s*"
    r"(?P<unit>%|percentage points?|відсот(?:ок|ки|ків)?|грн|uah|usd|руб|per\s+hour|на\s+годину)?",
    re.IGNORECASE,
)


def normalize_token(value: Any) -> str:
    return " ".join(str(value).casefold().split())[:160]


def temporal_anchors(value: str) -> tuple[str, ...]:
    """Return explicit temporal expressions only; never surrounding tokens."""
    anchors = {
        *(match.group(0).upper().replace("  ", " ") for match in _QUARTER.finditer(value)),
        *_DATE.findall(value),
        *_YEAR.findall(value),
    }
    return tuple(sorted(anchors))[:MAX_SCOPE_VALUES]


def numeric_facts(value: str) -> tuple[dict[str, Any], ...]:
    """Extract bounded values/units with explicit temporal context only."""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for match in _NUMBER.finditer(value):
        prefix = match.group("prefix") or ""
        scale = match.group("scale") or ""
        raw_unit = match.group("unit") or ""
        if not prefix and not scale and not raw_unit:
            continue
        number = normalize_numeric_value(match.group("value"))
        unit = normalize_numeric_unit(f"{prefix}{scale}{raw_unit}")
        window = value[max(0, match.start() - 80):match.end() + 80]
        periods = temporal_anchors(window)
        identity = (number, unit, periods)
        if identity in seen:
            continue
        seen.add(identity)
        facts.append({"value": number, "unit": unit, "periods": list(periods)})
        if len(facts) >= MAX_NUMERIC_FACTS:
            break
    return tuple(facts)


def _values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(sorted({normalize_token(item) for item in value if normalize_token(item)}))[:MAX_SCOPE_VALUES]


def _geography_anchors(raw: dict[str, Any]) -> tuple[dict[str, str], ...]:
    anchors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    raw_anchors = raw.get("geography_anchors")
    if isinstance(raw_anchors, (list, tuple)):
        for item in raw_anchors[:MAX_SCOPE_VALUES]:
            if not isinstance(item, dict):
                continue
            value = normalize_token(item.get("value", ""))
            level = normalize_token(item.get("level", "unspecified"))
            if not value or level not in GEOGRAPHY_LEVELS or (value, level) in seen:
                continue
            seen.add((value, level))
            anchors.append({"value": value, "level": level})
    for value in _values(raw.get("geography")):
        if not any(item["value"] == value for item in anchors):
            anchors.append({"value": value, "level": "unspecified"})
    return tuple(anchors[:MAX_SCOPE_VALUES])


def scope_from_evidence(evidence: Evidence) -> dict[str, Any]:
    existing = evidence.metadata.get(SCOPE_KEY)
    if isinstance(existing, dict) and existing.get("version") == SCOPE_VERSION:
        return _reconcile_persisted_numeric_scope(existing, (evidence,))

    return build_evidence_scope(
        metadata=evidence.metadata,
        statement=evidence.statement,
        source_excerpt=evidence.source_excerpt,
    )


def build_evidence_scope(
    *, metadata: dict[str, Any], statement: str, source_excerpt: str,
) -> dict[str, Any]:
    assignment = semantic_assignment(metadata) or {}
    period_source = metadata.get("observation_period")
    periods = temporal_anchors(period_source) if isinstance(period_source, str) else ()
    # Numeric fallback is permitted only from the already-grounded Evidence
    # statement/excerpt.  It never turns arbitrary context words into scope.
    grounded = f"{statement} {source_excerpt}"
    explicit_anchors = metadata.get("geography_anchors")
    geography = assignment.get("geography_applicability", ())
    anchor_values = (
        [item.get("value") for item in explicit_anchors if isinstance(item, dict)]
        if isinstance(explicit_anchors, (list, tuple)) else []
    )
    evidence_geography = list(geography) + anchor_values
    raw_numeric_facts = metadata.get("numeric_facts") or numeric_facts(grounded)
    evidence_numeric_facts = [
        {
            **dict(item),
            "geography": item.get("geography") or evidence_geography,
        }
        for item in raw_numeric_facts
        if isinstance(item, dict)
    ]
    return sanitize_scope({
        "version": SCOPE_VERSION,
        "geography": evidence_geography,
        "geography_anchors": explicit_anchors,
        "periods": periods,
        "metrics": metadata.get("metrics", metadata.get("metric", ())),
        "population_dimensions": metadata.get(
            "population_dimensions", metadata.get("population_dimension", ()),
        ),
        "numeric_facts": evidence_numeric_facts,
        "source": "validated_evidence_metadata",
    })


def combine_evidence_scopes(evidence: Iterable[Evidence]) -> dict[str, Any]:
    scopes = [scope_from_evidence(item) for item in evidence]
    return sanitize_scope({
        "version": SCOPE_VERSION,
        "geography": [item for scope in scopes for item in scope["geography"]],
        "geography_anchors": [
            item for scope in scopes for item in scope["geography_anchors"]
        ],
        "periods": [item for scope in scopes for item in scope["periods"]],
        "metrics": [item for scope in scopes for item in scope["metrics"]],
        "population_dimensions": [
            item for scope in scopes for item in scope["population_dimensions"]
        ],
        "numeric_facts": [item for scope in scopes for item in scope["numeric_facts"]],
        "source": "validated_evidence_bindings",
    })


def scope_for_finding(finding: Any, evidence_by_id: dict[str, Evidence]) -> dict[str, Any]:
    """Resolve one Finding's scope from persisted metadata or cited Evidence only."""
    evidence = tuple(
        evidence_by_id[ref]
        for ref in getattr(finding, "evidence_refs", ())
        if ref in evidence_by_id
    )
    existing = getattr(finding, "metadata", {}).get(SCOPE_KEY)
    if isinstance(existing, dict) and existing.get("version") == SCOPE_VERSION:
        return _reconcile_persisted_numeric_scope(existing, evidence)
    return combine_evidence_scopes(evidence)


def sanitize_scope(raw: dict[str, Any]) -> dict[str, Any]:
    anchors = _geography_anchors(raw)
    geography = tuple(sorted({item["value"] for item in anchors}))[:MAX_SCOPE_VALUES]
    raw_facts = raw.get("numeric_facts")
    facts: list[dict[str, Any]] = []
    if isinstance(raw_facts, (list, tuple)):
        for item in raw_facts[:MAX_NUMERIC_FACTS]:
            if not isinstance(item, dict):
                continue
            number = normalize_numeric_value(item.get("value", ""))
            unit = normalize_numeric_unit(item.get("unit", ""))
            if not number or not unit:
                continue
            facts.append({
                "value": number,
                "unit": unit,
                "periods": list(_values(item.get("periods"))),
                "geography": list(_values(item.get("geography"))),
                "metrics": list(_values(item.get("metrics"))),
                "population_dimensions": list(_values(item.get("population_dimensions"))),
            })
    return {
        "version": SCOPE_VERSION,
        "geography": list(geography),
        "geography_anchors": list(anchors),
        "periods": list(_values(raw.get("periods"))),
        "metrics": list(_values(raw.get("metrics"))),
        "population_dimensions": list(_values(raw.get("population_dimensions"))),
        "numeric_facts": facts,
        "source": normalize_token(raw.get("source", "")),
    }


def _reconcile_persisted_numeric_scope(
    raw: dict[str, Any], evidence: Iterable[Evidence],
) -> dict[str, Any]:
    """Repair only proven legacy decimal-collapse values from grounded Evidence.

    A persisted value is replaced only when the grounded statement/excerpt has
    no exact value for that unit and has exactly one decimal value whose
    punctuation-free form equals the persisted value. Ambiguous authority is
    retained unchanged and therefore remains fail-closed.
    """
    sanitized = sanitize_scope(raw)
    grounded = tuple(
        fact
        for item in evidence
        for fact in numeric_facts(f"{item.statement} {item.source_excerpt}")
    )
    rebuilt: list[dict[str, Any]] = []
    for fact in sanitized["numeric_facts"]:
        value = normalize_numeric_value(fact["value"])
        unit = normalize_numeric_unit(fact["unit"])
        candidates = [
            item for item in grounded
            if normalize_numeric_unit(item.get("unit", "")) == unit
        ]
        exact = [item for item in candidates if normalize_numeric_value(item.get("value", "")) == value]
        collapsed = [
            item for item in candidates
            if "." in normalize_numeric_value(item.get("value", ""))
            and normalize_numeric_value(item.get("value", "")).replace(".", "") == value
        ]
        replacement = collapsed[0] if not exact and len({normalize_numeric_value(item["value"]) for item in collapsed}) == 1 else None
        rebuilt.append({
            **fact,
            "value": normalize_numeric_value(replacement["value"]) if replacement else value,
            "unit": unit,
            "periods": fact["periods"] or (list(replacement.get("periods", ())) if replacement else []),
        })
    sanitized["numeric_facts"] = list({
        (
            item["value"], item["unit"], tuple(item["periods"]), tuple(item["geography"]),
            tuple(item["metrics"]), tuple(item["population_dimensions"]),
        ): item for item in rebuilt
    }.values())[:MAX_NUMERIC_FACTS]
    return sanitized
