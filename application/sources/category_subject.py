"""Deterministic Brief-level category-subject continuity (P1-23.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief

from application.sources.url_canonicalizer import normalize_query_text

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Domain-neutral research, geography, time, and task language.  These words
# cannot establish the market/category/entity being researched.
_NON_SUBJECT_WORDS = frozenset(
    {
        "about", "across", "analysis", "and", "are", "barrier", "barriers",
        "business", "category", "change", "changes", "context", "current",
        "data", "development", "driver", "drivers", "exploratory", "forecast",
        "for", "from", "future", "growth", "how", "including", "industry",
        "insight", "insights", "landscape", "latest", "main", "major", "market",
        "markets", "opportunities", "opportunity", "outlook", "overview", "policy",
        "research", "sector", "state", "structure", "study", "synthesis", "the",
        "through", "trend", "trends", "what", "where", "which", "with",
    }
)

_SUBJECT_MARKERS = frozenset({"category", "industry", "market", "markets", "sector"})
_MAX_SUBJECT_TOKENS = 5


@dataclass(frozen=True)
class CategorySubject:
    text: str
    tokens: frozenset[str]
    source: str


def resolve_category_subject(
    *,
    brief: ResearchBrief | None,
    design: ResearchDesign,
) -> CategorySubject | None:
    """Resolve one conservative, domain-neutral category subject.

    Canonical Brief evidence leads.  A hint is accepted only when it is also
    present in the business question (or the question is absent).  Legacy
    callers without a Brief retain the accepted shared-RQ fallback.  Ambiguous
    or over-broad results fail open.
    """
    if brief is not None:
        geography = _token_set(" ".join(brief.geography))
        timeframe = _token_set(brief.timeframe)
        excluded = geography | timeframe
        question_tokens = _subject_tokens(brief.business_question, excluded=excluded)

        canonical_hints = (
            (brief.market, "brief_market"),
            (" ".join(brief.target_entities), "brief_target_entities"),
        )
        for hint, source in canonical_hints:
            ordered = _ordered_subject_tokens(hint, excluded=excluded)
            if question_tokens and not question_tokens.intersection(ordered):
                continue
            subject = _build_subject(ordered, source=source)
            if subject is not None:
                return subject

        title_tokens = _ordered_subject_tokens(brief.title, excluded=excluded)
        if question_tokens:
            title_tokens = [token for token in title_tokens if token in question_tokens]
        subject = _build_subject(title_tokens, source="brief_title_business_question")
        if subject is not None:
            return subject

        local = _market_phrase_tokens(brief.business_question, excluded=excluded)
        subject = _build_subject(local, source="brief_business_question")
        if subject is not None:
            return subject

        return None

    return _resolve_from_design(design)


def _resolve_from_design(design: ResearchDesign) -> CategorySubject | None:
    question_sets = [
        set(_ordered_subject_tokens(question.question))
        for question in design.research_questions
        if question.question.strip()
    ]
    if not question_sets:
        return None
    shared = set.intersection(*question_sets)
    geography = _token_set(" ".join(need.geography for need in design.information_needs))
    timeframe = _token_set(" ".join(need.timeframe for need in design.information_needs))
    shared -= geography | timeframe
    ordered = [
        token
        for token in _ordered_subject_tokens(design.research_questions[0].question)
        if token in shared
    ]
    return _build_subject(ordered, source="research_question_intersection")


def _market_phrase_tokens(text: str, *, excluded: frozenset[str]) -> list[str]:
    raw = _raw_tokens(text)
    for index, token in enumerate(raw):
        if token not in _SUBJECT_MARKERS:
            continue
        before = [
            item
            for item in raw[max(0, index - _MAX_SUBJECT_TOKENS) : index]
            if item not in _NON_SUBJECT_WORDS and item not in excluded and not item.isdigit()
        ]
        if before:
            return before[-_MAX_SUBJECT_TOKENS:]
    return []


def _build_subject(tokens: list[str], *, source: str) -> CategorySubject | None:
    ordered = list(dict.fromkeys(tokens))
    if not ordered or len(ordered) > _MAX_SUBJECT_TOKENS:
        return None
    return CategorySubject(
        text=" ".join(ordered),
        tokens=frozenset(ordered),
        source=source,
    )


def _subject_tokens(text: str, *, excluded: frozenset[str]) -> frozenset[str]:
    return frozenset(_ordered_subject_tokens(text, excluded=excluded))


def _ordered_subject_tokens(
    text: str,
    *,
    excluded: frozenset[str] = frozenset(),
) -> list[str]:
    return [
        token
        for token in _raw_tokens(text)
        if token not in _NON_SUBJECT_WORDS
        and token not in excluded
        and not token.isdigit()
    ]


def _token_set(text: str) -> frozenset[str]:
    return frozenset(_raw_tokens(text))


def _raw_tokens(text: str) -> list[str]:
    normalized = normalize_query_text(str(text or "")).casefold()
    return [token for token in _TOKEN_RE.findall(normalized) if len(token) >= 3]
