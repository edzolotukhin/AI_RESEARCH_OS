from __future__ import annotations

from dataclasses import dataclass

from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, subject_tokens,
)
from domain.planning.research_design import ResearchDesign
from application.sources.expectation_aware_query_intent import render_aspect_query_terms

SUBJECT_RELEVANT = "subject_relevant"
SUBJECT_IRRELEVANT = "subject_irrelevant"
SUBJECT_UNRESOLVED = "subject_unresolved"

_UKRAINIAN_LANGUAGE_CODES = frozenset({"uk", "uk-ua", "ukrainian"})
_UKRAINIAN_ENDINGS = tuple(sorted({
    "ями", "ами", "ові", "еві", "ого", "ому", "ими", "ій", "ий", "а", "я",
    "у", "ю", "і", "ї", "и", "е", "є", "ої", "ом", "ем", "ам", "ям", "ах",
    "ях", "ою", "ею", "ки", "ка", "ку", "ок",
}, key=len, reverse=True))


def matches_subject_exclusion(subject: ResearchSubject, text: str) -> bool:
    combined = subject_tokens(text)
    return any(
        tokens and tokens <= combined
        for tokens in (subject_tokens(item) for item in subject.exclusions)
    )


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


def _lexeme_keys(text: str, *, language: str) -> set[str]:
    tokens = subject_tokens(text)
    if language.casefold() in _UKRAINIAN_LANGUAGE_CODES:
        return {_ukrainian_lexeme_key(token) for token in tokens}
    return set(tokens)


def _matches_aspect_semantics(
    text: str, *, aspect_id: str, need_text: str, question_text: str,
    language: str,
) -> bool:
    """Match one exact Design aspect without treating its ID as authority.

    The exact ID establishes scope only.  Positive grounding still comes from
    candidate text matching either the rendered aspect phrase or conservative
    lexical anchors shared by the linked IN/RQ context.
    """

    phrase = render_aspect_query_terms(aspect_id)
    if phrase:
        row = LexicalRepresentation(
            representation_id=f"aspect:{aspect_id}",
            language=language,
            label=phrase,
            normalized_phrases=(phrase,),
            concept_refs=(f"aspect:{aspect_id}",),
            provenance="current_design_required_aspect",
            approval_status="approved",
        )
        if _representation_matches(text, row):
            return True

    need_keys = _lexeme_keys(need_text, language=language)
    question_keys = _lexeme_keys(question_text, language=language)
    anchors = need_keys & question_keys
    text_keys = _lexeme_keys(text, language=language)
    overlap = anchors & text_keys
    required = 1 if len(anchors) == 1 else 2
    return bool(anchors) and len(overlap) >= required and any(
        len(item) >= 5 for item in overlap
    )


def assess_subject_text(*, subject: ResearchSubject, statement: str,
                        excerpt: str, information_need_id: str,
                        design: ResearchDesign | None = None) -> SubjectRelevanceDecision:
    if not subject.executable:
        return SubjectRelevanceDecision(SUBJECT_UNRESOLVED)
    if matches_subject_exclusion(subject, statement + " " + excerpt):
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

    # The exact grounded excerpt is allowed to carry explicit subject identity
    # for a context-dependent statement.  This is deliberately asymmetric:
    # statement-only identity cannot establish that the quoted source passage
    # supports the run's subject, and source-level relevance is not consulted.
    if excerpt_core:
        return SubjectRelevanceDecision(
            SUBJECT_RELEVANT, tuple(sorted(excerpt_core)),
            resolver_path="grounded_excerpt_lexical_representation_v1",
            matched_languages=tuple(sorted(
                _matching_languages(excerpt, core_rows)
            )),
        )

    for relation in subject.supporting_relations:
        if information_need_id not in relation.information_need_refs:
            continue
        approved = tuple(x for x in relation.lexical_representations
                         if x.approval_status.value == "approved")
        claim_relation = _matching_concepts(statement, approved)
        excerpt_relation = _matching_concepts(excerpt, approved)
        common = claim_relation & excerpt_relation
        if common:
            return SubjectRelevanceDecision(
                SUBJECT_RELEVANT, tuple(sorted(common)), relation.relation_id,
                matched_languages=tuple(sorted(
                    _matching_languages(statement, approved)
                    | _matching_languages(excerpt, approved)
                )),
            )
        if excerpt_relation:
            return SubjectRelevanceDecision(
                SUBJECT_RELEVANT, tuple(sorted(excerpt_relation)), relation.relation_id,
                resolver_path="grounded_excerpt_lexical_representation_v1",
                matched_languages=tuple(sorted(
                    _matching_languages(excerpt, approved)
                )),
            )
        if design is None or not relation.required_aspect_refs:
            continue
        need = next(
            (item for item in design.information_needs
             if item.id == information_need_id),
            None,
        )
        if need is None or need.evidence_expectation is None:
            continue
        allowed_aspects = set(need.evidence_expectation.required_aspects)
        question = next(
            (item for item in design.research_questions
             if item.id == need.research_question_id),
            None,
        )
        if question is None:
            continue
        for aspect_id in relation.required_aspect_refs:
            if aspect_id not in allowed_aspects:
                continue
            excerpt_match = _matches_aspect_semantics(
                excerpt,
                aspect_id=aspect_id,
                need_text=need.description,
                question_text=question.question,
                language=design.language,
            )
            if excerpt_match:
                return SubjectRelevanceDecision(
                    SUBJECT_RELEVANT,
                    (f"aspect:{aspect_id}",),
                    relation.relation_id,
                    resolver_path="grounded_excerpt_aspect_semantics_v1",
                    matched_languages=(design.language,),
                )
    return SubjectRelevanceDecision(SUBJECT_UNRESOLVED)


def subject_query_label(subject: ResearchSubject, language: str) -> str:
    if not subject.executable:
        raise ValueError("Approved executable ResearchSubject is required")
    for item in subject.approved_representations:
        if item.language.casefold() == str(language or "").casefold():
            return item.label
    return subject.canonical_label
