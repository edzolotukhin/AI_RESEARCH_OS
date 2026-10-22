from __future__ import annotations

from dataclasses import replace

from domain.planning.research_design import ResearchDesign

from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate
from application.evidence.relevance_validation import relevant_need_refs
from application.evidence.subject_relevance import SUBJECT_RELEVANT, assess_subject_text
from application.evidence.subject_relevance import matches_subject_exclusion
from application.evidence.semantic_assignment import (
    CONTRACT_VERSION,
    MAX_REQUIRED_ASPECT_REFS,
    MAX_SEMANTIC_JUSTIFICATION_CHARS,
    ValidatedSemanticAssignment,
)
from domain.planning.research_subject import subject_tokens
from application.research_scope.authoritative_scope import (
    SCOPE_KEY,
    build_evidence_scope,
)


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

    if candidate.contract_version is not None and candidate.contract_version != CONTRACT_VERSION:
        raise InvalidProvenanceError("Unsupported Evidence candidate contract version")

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

    if candidate.contract_version == CONTRACT_VERSION:
        return _validate_v2_candidate(
            candidate,
            validated_need_refs=validated_need_refs,
            need_by_id=need_by_id,
            question_by_id=question_by_id,
            design=design,
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
        subject_relevant: tuple[str, ...] = ()
        subject_decisions = {}
        for need_id in validated_need_refs:
            decision = assess_subject_text(
                subject=design.research_subject,
                statement=candidate.statement,
                excerpt=candidate.source_excerpt,
                information_need_id=need_id,
                design=design,
            )
            if decision.decision == SUBJECT_RELEVANT:
                subject_relevant = _append_unique(subject_relevant, need_id)
                subject_decisions[need_id] = decision
        if not subject_relevant:
            raise InvalidProvenanceError(
                "Candidate subject continuity is unsupported for assigned needs"
            )

        retained: tuple[str, ...] = ()
        for need_id in subject_relevant:
            decision = subject_decisions[need_id]
            need = need_by_id[need_id]
            allowed_aspects = set(
                need.evidence_expectation.required_aspects
                if need.evidence_expectation is not None else ()
            )
            aspect_grounded = (
                decision.resolver_path == "grounded_excerpt_aspect_semantics_v1"
                and any(
                    ref.removeprefix("aspect:") in allowed_aspects
                    for ref in decision.matched_concept_refs
                    if ref.startswith("aspect:")
                )
            )
            cross_language = any(
                language.casefold() != design.language.casefold()
                for language in decision.matched_languages
                if language and language != "und"
            )
            if need_id in locally_relevant_need_refs or cross_language or aspect_grounded:
                retained = _append_unique(retained, need_id)
        if not retained:
            raise InvalidProvenanceError(
                "Candidate local information-need relevance is unsupported for assigned needs"
            )
        validated_need_refs = retained
        accepted = subject_decisions[validated_need_refs[0]]
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
        contract_version=candidate.contract_version,
        required_aspect_refs=candidate.required_aspect_refs,
        subject_binding=candidate.subject_binding,
        semantic_justification=candidate.semantic_justification,
        geography_applicability=candidate.geography_applicability,
    )


def _validate_v2_candidate(
    candidate: EvidenceCandidate,
    *,
    validated_need_refs: tuple[str, ...],
    need_by_id: dict,
    question_by_id: dict,
    design: ResearchDesign,
) -> EvidenceCandidate:
    if len(validated_need_refs) != 1:
        raise InvalidProvenanceError("V2 candidate requires exactly one valid information need")
    need_id = validated_need_refs[0]
    need = need_by_id[need_id]
    question = question_by_id.get(need.research_question_id)
    if question is None:
        raise InvalidProvenanceError("V2 candidate references an unknown research question")

    refs = tuple(candidate.required_aspect_refs)
    if len(refs) > MAX_REQUIRED_ASPECT_REFS or len(refs) != len(set(refs)):
        raise InvalidProvenanceError("V2 required_aspect_refs are duplicate or excessive")
    allowed_aspects = set(
        need.evidence_expectation.required_aspects
        if need.evidence_expectation is not None else ()
    )
    if any(ref not in allowed_aspects for ref in refs):
        raise InvalidProvenanceError("V2 required aspect is outside the assigned information need")

    subject = design.research_subject
    if subject is None or not subject.executable:
        raise InvalidProvenanceError("V2 candidate requires an executable ResearchSubject")
    binding = candidate.subject_binding
    if not isinstance(binding, dict):
        raise InvalidProvenanceError("V2 subject_binding must be an object")
    binding_type = binding.get("binding_type")
    subject_id = binding.get("subject_id")
    subject_fingerprint = binding.get("subject_fingerprint")
    relation_id = binding.get("supporting_relation_id")
    if (
        subject_id != subject.subject_id
        or subject_fingerprint != subject.semantic_fingerprint
    ):
        raise InvalidProvenanceError("V2 candidate has a stale or unknown ResearchSubject")
    if binding_type == "canonical_subject":
        if relation_id not in (None, ""):
            raise InvalidProvenanceError("Canonical subject binding cannot name a relation")
        relation_id = None
    elif binding_type == "supporting_relation":
        if not isinstance(relation_id, str) or not relation_id:
            raise InvalidProvenanceError("Supporting relation binding requires a relation ID")
        relation = next(
            (item for item in subject.supporting_relations if item.relation_id == relation_id),
            None,
        )
        if relation is None or need_id not in relation.information_need_refs:
            raise InvalidProvenanceError("V2 supporting relation is outside the assigned information need")
        if relation.research_question_refs and need.research_question_id not in relation.research_question_refs:
            raise InvalidProvenanceError("V2 supporting relation is outside the assigned research question")
        if refs and any(ref not in relation.required_aspect_refs for ref in refs):
            raise InvalidProvenanceError("V2 supporting relation is outside the assigned aspect scope")
    else:
        raise InvalidProvenanceError("V2 subject binding type is invalid")

    justification = str(candidate.semantic_justification or "").strip()
    if not justification or len(justification) > MAX_SEMANTIC_JUSTIFICATION_CHARS:
        raise InvalidProvenanceError("V2 semantic justification is missing or excessive")
    geography = tuple(candidate.geography_applicability)
    if len(geography) != len(set(geography)) or len(geography) > 8:
        raise InvalidProvenanceError("V2 geography applicability is duplicate or excessive")
    allowed_geography = {
        value.strip()
        for value in (
            str(need.geography or ""),
            str(need.evidence_expectation.geography or "")
            if need.evidence_expectation is not None else "",
        )
        if value.strip()
    }
    if any(value not in allowed_geography for value in geography):
        raise InvalidProvenanceError("V2 geography applicability contradicts the assigned need")

    if matches_subject_exclusion(subject, candidate.statement + " " + candidate.source_excerpt):
        raise InvalidProvenanceError("V2 candidate matches an explicit ResearchSubject exclusion")
    if not _statement_excerpt_integrity(candidate.statement, candidate.source_excerpt):
        raise InvalidProvenanceError("V2 statement is unsupported by its grounded excerpt")

    lexical = assess_subject_text(
        subject=subject,
        statement=candidate.statement,
        excerpt=candidate.source_excerpt,
        information_need_id=need_id,
        design=design,
    )
    local_refs = relevant_need_refs(candidate, design=design)
    diagnostics = {
        "subject_decision": lexical.decision,
        "subject_resolver_path": lexical.resolver_path,
        "local_need_relevance": need_id in local_refs,
    }
    assignment = ValidatedSemanticAssignment(
        subject_id=subject.subject_id,
        subject_fingerprint=subject.semantic_fingerprint,
        binding_type=str(binding_type),
        supporting_relation_id=relation_id,
        information_need_id=need_id,
        required_aspect_refs=refs,
        geography_applicability=geography,
        semantic_justification=justification,
        lexical_diagnostics=diagnostics,
    )
    metadata = dict(candidate.metadata or {})
    metadata.pop("semantic_assignment", None)
    metadata["semantic_assignment"] = assignment.to_metadata()
    metadata[SCOPE_KEY] = build_evidence_scope(
        metadata=metadata, statement=candidate.statement,
        source_excerpt=candidate.source_excerpt,
    )
    return EvidenceCandidate(
        statement=candidate.statement,
        source_excerpt=candidate.source_excerpt,
        evidence_type=candidate.evidence_type,
        research_question_refs=(need.research_question_id,),
        information_need_refs=(need_id,),
        confidence=candidate.confidence,
        direct=candidate.direct,
        metadata=metadata,
        contract_version=CONTRACT_VERSION,
        required_aspect_refs=refs,
        subject_binding=dict(binding),
        semantic_justification=justification,
        geography_applicability=geography,
    )


def _statement_excerpt_integrity(statement: str, excerpt: str) -> bool:
    claim = set(subject_tokens(statement))
    quote = set(subject_tokens(excerpt))
    if not claim or not quote:
        return False
    shared_words = {token for token in claim & quote if len(token) >= 4}
    if shared_words:
        return True
    import re
    claim_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", statement))
    excerpt_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", excerpt))
    return bool(claim_numbers & excerpt_numbers)


def _append_unique(values: tuple[str, ...], item: str) -> tuple[str, ...]:
    if item in values:
        return values
    return values + (item,)
