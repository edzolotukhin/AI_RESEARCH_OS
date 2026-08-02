from __future__ import annotations

from domain.planning.research_design import ResearchDesign

from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate


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

    return EvidenceCandidate(
        statement=candidate.statement,
        source_excerpt=candidate.source_excerpt,
        evidence_type=candidate.evidence_type,
        research_question_refs=validated_question_refs,
        information_need_refs=validated_need_refs,
        confidence=candidate.confidence,
        direct=candidate.direct,
        metadata=dict(candidate.metadata or {}),
    )


def _append_unique(values: tuple[str, ...], item: str) -> tuple[str, ...]:
    if item in values:
        return values
    return values + (item,)
