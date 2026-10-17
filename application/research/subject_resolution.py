from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from application.sources.expectation_aware_query_intent import render_aspect_query_terms
from domain.planning.research_design import ResearchDesign
from domain.planning.research_subject import (
    ALLOWED_RELATION_TYPES, LexicalRepresentation, ResearchSubject,
    SupportingRelation, normalize_subject_text, subject_tokens,
)
from domain.research_brief import ResearchBrief


RELATION_REJECTION_CATEGORIES = (
    "malformed_shape",
    "invalid_relation_type",
    "missing_or_stale_information_need",
    "invalid_research_question_scope",
    "invalid_required_aspect_scope",
    "missing_semantic_grounding",
    "aspect_lexical_mismatch",
    "missing_lexical_representation",
)


_NON_GROUNDING_TOKENS = frozenset({
    "about", "analysis", "context", "data", "evidence", "information",
    "market", "measure", "measurement", "research", "study", "value", "values",
})


def _semantic_tokens(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        token for value in values for token in subject_tokens(value)
        if token not in _NON_GROUNDING_TOKENS
    )


def _relation_text(raw: dict) -> tuple[str, ...]:
    values = [str(raw.get("explanation") or "")]
    values.extend(str(item) for item in raw.get("concepts", ()))
    for item in raw.get("lexical_representations", ()):
        if isinstance(item, dict):
            values.append(str(item.get("label") or ""))
            values.extend(str(value) for value in item.get("normalized_phrases", ()))
    return tuple(values)


def _validated_relation(
    raw: dict, *, design: ResearchDesign, ordinal: int,
) -> tuple[SupportingRelation | None, str | None]:
    relation_id = str(raw.get("relation_id") or "").strip()
    relation_type = str(raw.get("relation_type") or "")
    if not relation_id:
        return None, "malformed_shape"
    if relation_type not in ALLOWED_RELATION_TYPES:
        return None, "invalid_relation_type"
    sequence_fields = (
        "information_need_refs", "research_question_refs", "required_aspect_refs",
        "concepts", "lexical_representations",
    )
    if any(
        field in raw and not isinstance(raw[field], (list, tuple))
        for field in sequence_fields
    ):
        return None, "malformed_shape"
    for representation in raw.get("lexical_representations", ()):
        if not isinstance(representation, dict):
            return None, "malformed_shape"
        if any(
            field in representation
            and not isinstance(representation[field], (list, tuple))
            for field in ("normalized_phrases", "concept_refs")
        ):
            return None, "malformed_shape"
    needs = {item.id: item for item in design.information_needs}
    questions = {item.id: item for item in design.research_questions}
    need_refs = tuple(dict.fromkeys(str(x) for x in raw.get("information_need_refs", ())))
    if not need_refs or any(ref not in needs for ref in need_refs):
        return None, "missing_or_stale_information_need"
    raw_question_refs = tuple(dict.fromkeys(
        str(x) for x in raw.get("research_question_refs", ())
    ))
    inferred_question_refs = tuple(dict.fromkeys(
        needs[ref].research_question_id for ref in need_refs
    ))
    question_refs = raw_question_refs or inferred_question_refs
    if (any(ref not in questions for ref in question_refs)
            or any(needs[ref].research_question_id not in question_refs for ref in need_refs)):
        return None, "invalid_research_question_scope"
    allowed_aspects = tuple(dict.fromkeys(
        aspect
        for ref in need_refs
        for aspect in (
            needs[ref].evidence_expectation.required_aspects
            if needs[ref].evidence_expectation is not None else ()
        )
    ))
    raw_aspects = tuple(dict.fromkeys(
        str(x) for x in raw.get("required_aspect_refs", ())
    ))
    if raw_aspects and any(aspect not in allowed_aspects for aspect in raw_aspects):
        return None, "invalid_required_aspect_scope"
    relation_tokens = _semantic_tokens(_relation_text(raw))
    if not relation_tokens:
        return None, "missing_semantic_grounding"
    matched_aspects = tuple(
        aspect for aspect in allowed_aspects
        if relation_tokens & _semantic_tokens((render_aspect_query_terms(aspect),))
    )
    aspect_refs = raw_aspects or matched_aspects
    design_tokens = _semantic_tokens(
        tuple(needs[ref].description for ref in need_refs)
        + tuple(questions[ref].question for ref in question_refs)
    )
    if not matched_aspects and not (relation_tokens & design_tokens):
        return None, "missing_semantic_grounding"
    relation_concepts = tuple(dict.fromkeys(
        str(x) for x in raw.get("concepts", ()) if str(x).strip()
    )) or (f"support-{ordinal}",)
    representations = tuple(
        LexicalRepresentation(
            representation_id=str(
                item.get("representation_id") or f"{relation_id}-representation-{index}"
            ),
            language=str(item.get("language") or "und"),
            label=str(item.get("label") or ""),
            normalized_phrases=tuple(
                item.get("normalized_phrases") or (item.get("label") or "",)
            ),
            concept_refs=tuple(item.get("concept_refs") or relation_concepts),
            provenance="planner_proposal",
        )
        for index, item in enumerate(raw.get("lexical_representations", ()), start=1)
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    )
    if not representations:
        return None, "missing_lexical_representation"
    return SupportingRelation(
        relation_id=relation_id,
        relation_type=relation_type,
        information_need_refs=need_refs,
        concepts=relation_concepts,
        lexical_representations=representations,
        explanation=str(raw.get("explanation") or ""),
        research_question_refs=question_refs,
        required_aspect_refs=aspect_refs,
    ), None


def _resolve_relations(
    proposal: dict, *, design: ResearchDesign | None,
) -> tuple[tuple[SupportingRelation, ...], dict[str, object]]:
    raw_relations = proposal.get("supporting_relations", ())
    if not isinstance(raw_relations, (list, tuple)):
        rows = (raw_relations,)
    else:
        rows = tuple(raw_relations)
    rejection_counts = {category: 0 for category in RELATION_REJECTION_CATEGORIES}
    accepted: list[SupportingRelation] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict) or design is None:
            rejection_counts["malformed_shape"] += 1
            continue
        relation, rejection = _validated_relation(raw, design=design, ordinal=index)
        if relation is not None:
            accepted.append(relation)
        else:
            rejection_counts[rejection or "malformed_shape"] += 1
    rejected = len(rows) - len(accepted)
    diagnostics: dict[str, object] = {
        "subject_proposal_present": True,
        "proposed_relation_count": len(rows),
        "accepted_relation_count": len(accepted),
        "rejected_relation_count": rejected,
        "rejection_category_counts": rejection_counts,
    }
    return tuple(accepted), diagnostics


def _validated_aliases(
    proposal: dict, *, canonical: str, canonical_matches: bool,
    design: ResearchDesign | None,
) -> tuple[tuple[str, str], ...]:
    rows = tuple(
        (str(item.get("language") or "und"), str(item.get("label") or "").strip())
        for item in proposal.get("lexical_representations", ())
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    )
    if canonical_matches:
        return rows
    if design is None:
        return ()
    grounding = _semantic_tokens(
        (canonical,)
        + tuple(question.question for question in design.research_questions)
        + tuple(need.description for need in design.information_needs)
        + tuple(
            render_aspect_query_terms(aspect)
            for need in design.information_needs
            if need.evidence_expectation is not None
            for aspect in need.evidence_expectation.required_aspects
        )
    )
    return tuple(row for row in rows if _semantic_tokens((row[1],)) & grounding)


def resolve_subject_proposal(
    brief: ResearchBrief, proposal: dict | None = None, *,
    design: ResearchDesign | None = None,
) -> ResearchSubject:
    explicit = str(brief.market or "").strip()
    fallback = str(brief.title or "").strip()
    canonical = explicit or fallback
    if proposal:
        proposed_label = str(proposal.get("canonical_label") or "").strip()
        canonical_matches = not (
            explicit and proposed_label
            and normalize_subject_text(explicit) != normalize_subject_text(proposed_label)
        )
        aliases = _validated_aliases(
            proposal, canonical=canonical, canonical_matches=canonical_matches,
            design=design,
        )
        relations, relation_diagnostics = _resolve_relations(proposal, design=design)
        subject = ResearchSubject.proposed(
            canonical_label=canonical or proposed_label,
            canonical_language=str(proposal.get("canonical_language") or brief.language),
            aliases=aliases,
            provenance=("planner_proposal" if canonical_matches
                        else "brief_market_planner_mismatch_scoped"),
            supporting_relations=relations,
            exclusions=tuple(str(x) for x in proposal.get("exclusions", ())),
        )
        return replace_subject_provenance(subject, relation_diagnostics)
    subject = ResearchSubject.proposed(
        canonical_label=canonical,
        canonical_language=brief.language,
        provenance="brief_market" if explicit else "brief_title_fallback",
    )
    return replace_subject_provenance(subject, {
        "subject_proposal_present": False,
        "proposed_relation_count": 0,
        "accepted_relation_count": 0,
        "rejected_relation_count": 0,
        "rejection_category_counts": {
            category: 0 for category in RELATION_REJECTION_CATEGORIES
        },
    })


def replace_subject_provenance(
    subject: ResearchSubject, diagnostics: dict[str, object],
) -> ResearchSubject:
    return replace(
        subject,
        provenance={
            **dict(subject.provenance or {}),
            "relation_diagnostics": diagnostics,
        },
        semantic_fingerprint="",
    )
