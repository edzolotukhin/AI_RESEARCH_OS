from __future__ import annotations

from dataclasses import dataclass

from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, subject_tokens,
)

SUBJECT_RELEVANT = "subject_relevant"
SUBJECT_IRRELEVANT = "subject_irrelevant"
SUBJECT_UNRESOLVED = "subject_unresolved"

_UKRAINIAN_LANGUAGE_CODES = frozenset({"uk", "uk-ua", "ukrainian"})
_UKRAINIAN_ENDINGS = tuple(sorted({
    "ями", "ами", "ові", "еві", "ого", "ому", "ими", "ій", "ий", "а", "я",
    "у", "ю", "і", "ї", "и", "е", "є", "ом", "ем", "ам", "ям", "ах",
    "ях", "ою", "ею", "ки", "ка", "ку", "ок",
}, key=len, reverse=True))


def _ukrainian_lexeme_key(token: str) -> str:
    """Return a conservative deterministic key for Ukrainian inflection.

    This is deliberately not fuzzy matching and contains no domain vocabulary.
    It normalizes productive endings only; semantic aliases still have to be
    explicit approved ``LexicalRepresentation`` rows.
    """

    value = token
    for ending in _UKRAINIAN_ENDINGS:
        if value.endswith(ending) and len(value) - len(ending) >= 4:
            value = value[: -len(ending)]
            break
    # Adjectival forms such as ``-альний/-альна/-альні`` and their derived
    # noun forms share this productive Ukrainian base after inflection removal.
    if value.endswith("альн") and len(value) > 6:
        value = value[:-4]
    if value.endswith("к") and len(value) > 5:
        value = value[:-1]
    return value


def _representation_matches(text: str, row: LexicalRepresentation) -> bool:
    text_tokens = subject_tokens(text)
    for phrase in row.normalized_phrases:
        phrase_tokens = subject_tokens(phrase)
        if phrase_tokens and phrase_tokens <= text_tokens:
            return True
        if row.language.casefold() not in _UKRAINIAN_LANGUAGE_CODES:
            continue
        phrase_keys = {_ukrainian_lexeme_key(token) for token in phrase_tokens}
        text_keys = {_ukrainian_lexeme_key(token) for token in text_tokens}
        overlap = phrase_keys & text_keys
        # A multi-token category can be represented by its distinctive derived
        # noun (for example an adjective+noun category collapsed to one noun),
        # but only when at least half of its lexical keys agree exactly.
        required = max(1, (len(phrase_keys) + 1) // 2)
        if len(overlap) >= required and any(len(item) >= 5 for item in overlap):
            return True
    return False


@dataclass(frozen=True)
class SubjectRelevanceDecision:
    decision: str
    matched_concept_refs: tuple[str, ...] = ()
    supporting_relation_id: str | None = None
    resolver_path: str = "approved_lexical_representation_v1"
    matched_languages: tuple[str, ...] = ()


def _matching_concepts(text: str, rows: tuple[LexicalRepresentation, ...]) -> set[str]:
    matched: set[str] = set()
    for row in rows:
        if _representation_matches(text, row):
            matched.update(row.concept_refs)
    return matched


def _matching_languages(text: str, rows: tuple[LexicalRepresentation, ...]) -> set[str]:
    return {
        row.language for row in rows
        if _representation_matches(text, row)
    }


def assess_subject_text(*, subject: ResearchSubject, statement: str,
                        excerpt: str, information_need_id: str) -> SubjectRelevanceDecision:
    if not subject.executable:
        return SubjectRelevanceDecision(SUBJECT_UNRESOLVED)
    exclusion_tokens = tuple(subject_tokens(item) for item in subject.exclusions)
    combined = subject_tokens(statement + " " + excerpt)
    if any(tokens and tokens <= combined for tokens in exclusion_tokens):
        return SubjectRelevanceDecision(SUBJECT_IRRELEVANT)

    core_rows = subject.approved_representations
    claim_core = _matching_concepts(statement, core_rows)
    excerpt_core = _matching_concepts(excerpt, core_rows)
    common = claim_core & excerpt_core
    if common:
        return SubjectRelevanceDecision(
            SUBJECT_RELEVANT, tuple(sorted(common)),
            matched_languages=tuple(sorted(
                _matching_languages(statement, core_rows)
                | _matching_languages(excerpt, core_rows)
            )),
        )

    for relation in subject.supporting_relations:
        if information_need_id not in relation.information_need_refs:
            continue
        approved = tuple(x for x in relation.lexical_representations
                         if x.approval_status.value == "approved")
        common = _matching_concepts(statement, approved) & _matching_concepts(excerpt, approved)
        if common:
            return SubjectRelevanceDecision(
                SUBJECT_RELEVANT, tuple(sorted(common)), relation.relation_id,
                matched_languages=tuple(sorted(
                    _matching_languages(statement, approved)
                    | _matching_languages(excerpt, approved)
                )),
            )
    return SubjectRelevanceDecision(SUBJECT_UNRESOLVED)


def subject_query_label(subject: ResearchSubject, language: str) -> str:
    if not subject.executable:
        raise ValueError("Approved executable ResearchSubject is required")
    for item in subject.approved_representations:
        if item.language.casefold() == str(language or "").casefold():
            return item.label
    return subject.canonical_label
