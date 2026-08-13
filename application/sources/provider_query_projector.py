from __future__ import annotations

import re

from application.sources.url_canonicalizer import normalize_query_text

MAX_PROVIDER_QUERY_CHARS = 220
MAX_TIMEFRAME_CHARS = 48

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def project_provider_query_text(
    *,
    category_subject: str | None,
    geography: str | None,
    core_intent: str | None,
    timeframe: str | None = None,
    targeted_intent: str | None = None,
) -> str | None:
    """Build one bounded, provider-facing query from structured semantics.

    ``None`` means projection was not demonstrably safe; callers must fail open
    to the complete internal SearchQuery. Bounds drop whole optional semantic
    units and never slice through a unit.
    """

    category = normalize_query_text(category_subject or "")
    geo = _concise_geography(geography or "")
    intent = _core_intent(core_intent or "")
    if not category or not geo or not intent:
        return None

    required_units = (category, geo, intent)
    required = normalize_query_text(" ".join(required_units))
    if len(required) > MAX_PROVIDER_QUERY_CHARS:
        return None

    units = list(required_units)
    target = _core_intent(targeted_intent or "")
    if target:
        target = _remove_duplicate_phrase(target, category)
        target = _remove_duplicate_phrase(target, geo)
        target = _remove_duplicate_phrase(target, intent)
        if target and len(normalize_query_text(" ".join((*units, target)))) <= MAX_PROVIDER_QUERY_CHARS:
            units.append(target)

    time = normalize_query_text(timeframe or "")
    if (
        time
        and len(time) <= MAX_TIMEFRAME_CHARS
        and _YEAR_RE.search(time)
        and len(normalize_query_text(" ".join((*units, time)))) <= MAX_PROVIDER_QUERY_CHARS
    ):
        units.append(time)

    projected = normalize_query_text(" ".join(units))
    return projected or None


def _concise_geography(value: str) -> str:
    normalized = normalize_query_text(value)
    if not normalized:
        return ""
    return normalize_query_text(re.split(r"[;(]", normalized, maxsplit=1)[0])


def _core_intent(value: str) -> str:
    normalized = normalize_query_text(value)
    if not normalized:
        return ""
    return _SENTENCE_BOUNDARY_RE.split(normalized, maxsplit=1)[0].rstrip(".!?")


def _remove_duplicate_phrase(value: str, phrase: str) -> str:
    if not value or not phrase:
        return value
    pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)
    return normalize_query_text(pattern.sub(" ", value))
