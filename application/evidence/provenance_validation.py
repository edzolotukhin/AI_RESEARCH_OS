from __future__ import annotations

from dataclasses import replace

from domain.planning.research_design import ResearchDesign

from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate
from application.evidence.relevance_validation import relevant_need_refs
from application.evidence.subject_relevance import SUBJECT_RELEVANT, assess_subject_text


class InvalidProvenanceError(ValueError):
    """Raised when extractor output references IDs outside the run/design scope."""


def validate_candidate_provenance(
    candidate: EvidenceCandidate,
    *,
    run_context: RunScopedSourceContext,
    design: ResearchDesign,
) -> EvidenceCandidate:
    """Replace extractor refs with authoritative run/design-validated provenance."""
    allowed_needs = set(run_context.information_need_ids)
    if not allowed_needs:
        raise InvalidProvenanceError(
            "No information needs are linked to this source for the current run",
        )

    need_by_id = {need.id: need for need in design.information_needs}
    question_by_id = {question.id: question for question in design.research_questions}

    validated_need_refs: tuple[str, ...] = ()
    for need_id in candidate.information_need_refs:
        if need_id not in allowed_needs:
            continue
        need = need_by_id.get(need_id)
        if need is None:
            raise InvalidProvenanceError(
                f"Information need {need_id!r} is not in the run design",
            )
        validated_need_refs = _append_unique(validated_need_refs, need_id)

    if not validated_need_refs:
        raise InvalidProvenanceError(
            "Candidate information_need_refs are outside the run-scoped context",
        )

    locally_relevant_need_refs = relevant_need_refs(
        replace(candidate, information_need_refs=validated_need_refs), design=design,
    )
    if design.research_subject is None and not locally_relevant_need_refs:
        raise InvalidProvenanceError(
            "Candidate subject relevance is unsupported for assigned needs (local relevance)"
        )
    if design.research_subject is None:
        validated_need_refs = locally_relevant_need_refs

    subject_metadata = None
    if design.research_subject is not None:
        retained: tuple[str, ...] = ()
        accepted_decisions = []
        for need_id in validated_need_refs:
            decision = assess_subject_text(
                subject=design.research_subject,
                statement=candidate.statement,
                excerpt=candidate.source_excerpt,
                information_need_id=need_id,
            )
            cross_language = any(
                language.casefold() != design.language.casefold()
                for language in decision.matched_languages
                if language and language != "und"
            )
            if decision.decision == SUBJECT_RELEVANT and (
                need_id in locally_relevant_need_refs or cross_language
            ):
                retained = _append_unique(retained, need_id)
                accepted_decisions.append(decision)
        validated_need_refs = retained
        if not validated_need_refs:
            raise InvalidProvenanceError(
                "Candidate subject relevance is unsupported for assigned needs"
            )
        accepted = accepted_decisions[0]
        subject_metadata = {
            "subject_id": design.research_subject.subject_id,
            "subject_version": design.research_subject.version,
            "subject_fingerprint": design.research_subject.semantic_fingerprint,
            "subject_decision": accepted.decision,
            "matched_concept_refs": list(accepted.matched_concept_refs),
            "resolver_path": accepted.resolver_path,
            "matched_languages": list(accepted.matched_languages),
        }
        if accepted.supporting_relation_id:
            subject_metadata["supporting_relation_id"] = accepted.supporting_relation_id

    validated_question_refs: tuple[str, ...] = ()
    for need_id in validated_need_refs:
        need = need_by_id[need_id]
        if need.research_question_id not in question_by_id:
            raise InvalidProvenanceError(
                f"Research question {need.research_question_id!r} is not in the run design",
            )
        validated_question_refs = _append_unique(
            validated_question_refs,
            need.research_question_id,
        )

    metadata = dict(candidate.metadata or {})
    metadata.pop("research_subject", None)
    metadata.pop("_research_subject_audit", None)
    if subject_metadata is not None:
        metadata["_research_subject_audit"] = subject_metadata
    return EvidenceCandidate(
        statement=candidate.statement,
        source_excerpt=candidate.source_excerpt,
        evidence_type=candidate.evidence_type,
        research_question_refs=validated_question_refs,
        information_need_refs=validated_need_refs,
        confidence=candidate.confidence,
        direct=candidate.direct,
        metadata=metadata,
    )


def _append_unique(values: tuple[str, ...], item: str) -> tuple[str, ...]:
    if item in values:
        return values
    return values + (item,)
