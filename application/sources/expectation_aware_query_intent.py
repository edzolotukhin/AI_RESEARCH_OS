from __future__ import annotations

from collections.abc import Sequence

from application.sources.url_canonicalizer import normalize_query_text
from domain.research_quality.semantic_decision_normalizer import LEGACY_NEED_ASPECT_ID


def render_aspect_query_terms(aspect_id: str) -> str:
    """Deterministic web-search phrasing for a canonical aspect identifier.

    required_aspects are identifiers only (no display-label catalog). Underscores
    and hyphens become spaces. Internal sentinel IDs are omitted.
    """
    text = str(aspect_id).strip()
    if not text or text == LEGACY_NEED_ASPECT_ID:
        return ""
    if text.startswith("__") and text.endswith("__"):
        return ""
    rendered = text.replace("_", " ").replace("-", " ")
    return normalize_query_text(rendered)


def build_expectation_aware_query_text(
    *,
    description: str,
    geography: str | None = None,
    timeframe: str | None = None,
    semantic_targets: Sequence[str] = (),
    subject_context: str | None = None,
    category_context: str | None = None,
) -> str:
    """Compose one deterministic Search query carrying semantic aspect intent.

    Order: optional subject/topic context, need description, unique aspect
    phrases, geography, timeframe. Identical inputs always yield identical
    text. Pure application logic.

    ``subject_context`` carries the parent ResearchQuestion (or equivalent
    category anchor). Initial Search (P1-21.1) and targeted Search both pass
    it when a parent question is available. Omitting it remains a deterministic
    fallback for callers that have no parent subject.
    """
    parts: list[str] = []
    seen_phrases: set[str] = set()

    def _append(fragment: str) -> None:
        text = normalize_query_text(fragment)
        if not text:
            return
        key = text.casefold()
        if key in seen_phrases:
            return
        blob = " ".join(parts).casefold()
        if blob and key in blob:
            return
        seen_phrases.add(key)
        parts.append(text)

    if subject_context:
        _append(subject_context)
    if category_context:
        _append(category_context)
    _append(description)
    for aspect_id in semantic_targets:
        _append(render_aspect_query_terms(aspect_id))
    if geography:
        _append(str(geography))
    if timeframe:
        _append(str(timeframe))
    return normalize_query_text(" ".join(parts))
