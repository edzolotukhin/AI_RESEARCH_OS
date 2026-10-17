from dataclasses import replace

import pytest

from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate
from application.research.subject_resolution import resolve_subject_proposal
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief


def _design() -> ResearchDesign:
    base = ResearchDesign(
        id="ow20f",
        language="uk",
        research_questions=(
            ResearchQuestion("rq-income", "Як змінилася реальна заробітна плата працівників?"),
            ResearchQuestion("rq-prices", "Як змінилися споживчі ціни домогосподарств?"),
        ),
        information_needs=(
            InformationNeed(
                "in-income", "rq-income",
                "Встановити динаміку реальної заробітної плати працівників",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("реальна_заробітна_плата",),
                ),
            ),
            InformationNeed(
                "in-prices", "rq-prices",
                "Встановити динаміку споживчих цін домогосподарств",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("споживчі_ціни",),
                ),
            ),
        ),
        source_strategy=("official statistics",),
        analysis_plan=("compare",),
        deliverable_plan=("report",),
    )
    proposal = {
        "canonical_label": "Добробут домогосподарств",
        "canonical_language": "uk",
        "lexical_representations": [
            {"language": "uk", "label": "добробут домогосподарств"},
        ],
        "supporting_relations": [{
            "relation_id": "income-context",
            "relation_type": "economic_context",
            "information_need_refs": ["in-income"],
            "research_question_refs": ["rq-income"],
            "required_aspect_refs": ["реальна_заробітна_плата"],
            "concepts": ["income-context"],
            "lexical_representations": [{
                "representation_id": "income-context-uk",
                "language": "uk",
                "label": "економічна стійкість",
                "normalized_phrases": ["економічна стійкість"],
                "concept_refs": ["income-context"],
            }],
            "explanation": "Контекст показників працівників",
        }],
        "exclusions": ["криптовалютні активи"],
    }
    subject = resolve_subject_proposal(
        ResearchBrief(
            title="Добробут", business_question="Як змінився добробут?",
            market="Добробут домогосподарств", language="uk",
        ),
        proposal,
        design=base,
    ).approve()
    return replace(base, research_subject=subject)


def _candidate(text: str, need: str = "in-income") -> EvidenceCandidate:
    return EvidenceCandidate(
        statement=text,
        source_excerpt=text,
        evidence_type="direct_excerpt",
        research_question_refs=(),
        information_need_refs=(need,),
    )


def _validate(text: str, need: str = "in-income"):
    question = "rq-income" if need == "in-income" else "rq-prices"
    return validate_candidate_provenance(
        _candidate(text, need),
        design=_design(),
        run_context=RunScopedSourceContext(
            "run", "ow20f", (need,), (question,), ("sq",),
        ),
    )


def test_core_subject_path_is_unchanged():
    assert _validate(
        "Добробут домогосподарств і реальна заробітна плата покращилися."
    ).information_need_refs == (
        "in-income",
    )


def test_relation_lexical_path_is_unchanged():
    result = _validate("Економічна стійкість працівників покращилася.")
    assert result.metadata["_research_subject_audit"]["supporting_relation_id"] == (
        "income-context"
    )


def test_exact_referenced_aspect_semantics_are_accepted_without_relation_phrase():
    result = _validate("Реальна заробітна плата працівників зросла.")
    audit = result.metadata["_research_subject_audit"]
    assert audit["supporting_relation_id"] == "income-context"
    assert audit["resolver_path"] == "grounded_excerpt_aspect_semantics_v1"


def test_ukrainian_inflection_of_referenced_aspect_is_accepted():
    result = _validate("Зростання реальної заробітної плати працівника прискорилося.")
    assert result.metadata["_research_subject_audit"]["resolver_path"] == (
        "grounded_excerpt_aspect_semantics_v1"
    )


def test_valid_aspect_reference_does_not_accept_unrelated_text():
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        _validate("Продаж автомобілів преміумкласу збільшився.")


def test_aspect_from_another_information_need_is_rejected():
    with pytest.raises(InvalidProvenanceError):
        _validate("Споживчі ціни домогосподарств зросли.", "in-income")


def test_stale_aspect_reference_is_rejected():
    design = _design()
    relation = replace(
        design.research_subject.supporting_relations[0],
        required_aspect_refs=("stale_aspect",),
    )
    subject = replace(
        design.research_subject,
        supporting_relations=(relation,),
        semantic_fingerprint="",
    )
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        validate_candidate_provenance(
            _candidate("Stale aspect"),
            design=replace(design, research_subject=subject),
            run_context=RunScopedSourceContext(
                "run", "ow20f", ("in-income",), ("rq-income",), ("sq",),
            ),
        )


def test_exclusion_overrides_aspect_semantic_match():
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        _validate("Реальна заробітна плата та криптовалютні активи зросли.")
