from __future__ import annotations

from uuid import uuid4

from domain.planning.research_subject import (
    LexicalRepresentation, ResearchSubject, SupportingRelation,
    normalize_subject_text,
)
from domain.research_brief import ResearchBrief


def resolve_subject_proposal(brief: ResearchBrief, proposal: dict | None = None) -> ResearchSubject:
    explicit = str(brief.market or "").strip()
    fallback = str(brief.title or "").strip()
    canonical = explicit or fallback
    if proposal:
        proposed_label = str(proposal.get("canonical_label") or "").strip()
        if explicit and proposed_label and normalize_subject_text(explicit) != normalize_subject_text(proposed_label):
            return ResearchSubject.proposed(
                canonical_label=explicit, canonical_language=brief.language,
                provenance="brief_market_planner_mismatch_ignored",
            )
        aliases = tuple(
            (str(item.get("language") or "und"), str(item.get("label") or ""))
            for item in proposal.get("lexical_representations", ())
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        )
        relations = []
        for raw in proposal.get("supporting_relations", ()):
            if not isinstance(raw, dict):
                continue
            relation_concepts = tuple(str(x) for x in raw.get("concepts", ())) or (
                f"support-{len(relations) + 1}",
            )
            representations = tuple(
                LexicalRepresentation(
                    representation_id=str(uuid4()),
                    language=str(item.get("language") or "und"),
                    label=str(item.get("label") or ""),
                    normalized_phrases=tuple(item.get("normalized_phrases") or (item.get("label") or "",)),
                    concept_refs=tuple(item.get("concept_refs") or relation_concepts),
                    provenance="planner_proposal",
                )
                for item in raw.get("lexical_representations", ())
                if isinstance(item, dict) and str(item.get("label") or "").strip()
            )
            relations.append(SupportingRelation(
                relation_id=str(raw.get("relation_id") or uuid4()),
                relation_type=str(raw.get("relation_type") or ""),
                information_need_refs=tuple(str(x) for x in raw.get("information_need_refs", ())),
                concepts=relation_concepts,
                lexical_representations=representations,
                explanation=str(raw.get("explanation") or ""),
            ))
        return ResearchSubject.proposed(
            canonical_label=canonical or proposed_label,
            canonical_language=str(proposal.get("canonical_language") or brief.language),
            aliases=aliases,
            provenance="planner_proposal",
            supporting_relations=tuple(relations),
            exclusions=tuple(str(x) for x in proposal.get("exclusions", ())),
        )
    return ResearchSubject.proposed(
        canonical_label=canonical,
        canonical_language=brief.language,
        provenance="brief_market" if explicit else "brief_title_fallback",
    )
