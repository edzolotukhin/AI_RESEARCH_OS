from __future__ import annotations

from dataclasses import dataclass

from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, subject_tokens,
)

SUBJECT_RELEVANT = "subject_relevant"
SUBJECT_IRRELEVANT = "subject_irrelevant"
SUBJECT_UNRESOLVED = "subject_unresolved"


@dataclass(frozen=True)
class SubjectRelevanceDecision:
    decision: str
    matched_concept_refs: tuple[str, ...] = ()
    supporting_relation_id: str | None = None
    resolver_path: str = "approved_lexical_representation_v1"
    matched_languages: tuple[str, ...] = ()


def _matching_concepts(text: str, rows: tuple[LexicalRepresentation, ...]) -> set[str]:
    tokens = subject_tokens(text)
    matched: set[str] = set()
    for row in rows:
        for phrase in row.normalized_phrases:
            phrase_tokens = subject_tokens(phrase)
            if phrase_tokens and phrase_tokens <= tokens:
                matched.update(row.concept_refs)
                break
    return matched


def _matching_languages(text: str, rows: tuple[LexicalRepresentation, ...]) -> set[str]:
    tokens = subject_tokens(text)
    return {
        row.language for row in rows
        if any(subject_tokens(phrase) and subject_tokens(phrase) <= tokens
               for phrase in row.normalized_phrases)
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
