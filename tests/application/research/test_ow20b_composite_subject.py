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


def _design():
    return ResearchDesign(
        id="design-composite",
        language="en",
        research_questions=(
            ResearchQuestion("rq-a", "How do household resources change?"),
            ResearchQuestion("rq-b", "What pressures affect household budgets?"),
            ResearchQuestion("rq-c", "What are current labour conditions?"),
        ),
        information_needs=(
            InformationNeed(
                "in-a", "rq-a", "Establish the trend in household resources",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("nominal_earnings", "real_earnings"),
                ),
            ),
            InformationNeed(
                "in-b", "rq-b", "Establish pressure on household budgets",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("consumer_price_growth", "purchasing_power"),
                ),
            ),
            InformationNeed(
                "in-c", "rq-c", "Establish labour-market conditions",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("employment", "unemployment"),
                ),
            ),
        ),
        source_strategy=("official statistics",),
        analysis_plan=("compare",),
        deliverable_plan=("report",),
    )


def _relation(identity, need, aspect, label, *, question=None):
    return {
        "relation_id": identity,
        "relation_type": "economic_context",
        "information_need_refs": [need],
        "research_question_refs": [question or need.replace("in-", "rq-")],
        "required_aspect_refs": [aspect],
        "concepts": [identity],
        "lexical_representations": [{
            "representation_id": f"{identity}-en",
            "language": "en",
            "label": label,
            "normalized_phrases": [label],
        }],
        "explanation": f"{label} is required by {aspect}",
    }


def _proposal():
    return {
        "canonical_label": "Household financial position",
        "canonical_language": "en",
        "lexical_representations": [
            {"language": "en", "label": "consumer financial wellbeing"},
            {"language": "en", "label": "unrelated automotive category"},
        ],
        "supporting_relations": [
            _relation("earnings", "in-a", "real_earnings", "real earnings"),
            _relation("prices", "in-b", "consumer_price_growth", "consumer price growth"),
            _relation("labour", "in-c", "unemployment", "unemployment"),
            _relation("stale", "in-missing", "unknown", "unrelated concept"),
            _relation("wrong-aspect", "in-a", "consumer_price_growth", "consumer price growth"),
            {
                **_relation("malformed", "in-a", "real_earnings", "real earnings"),
                "lexical_representations": [{
                    "language": "en",
                    "label": "real earnings",
                    "normalized_phrases": "real earnings",
                }],
            },
        ],
        "exclusions": [],
    }


def _resolved_design():
    design = _design()
    subject = resolve_subject_proposal(
        ResearchBrief(
            title="Financial wellbeing study",
            business_question="How is wellbeing changing?",
            market="Consumer financial wellbeing",
            language="en",
        ),
        _proposal(),
        design=design,
    ).approve()
    return replace(design, research_subject=subject)


def _candidate(text, need):
    return EvidenceCandidate(
        statement=text,
        source_excerpt=text,
        evidence_type="direct_excerpt",
        research_question_refs=(),
        information_need_refs=(need,),
    )


def _context(need, question):
    return RunScopedSourceContext(
        "run", "design-composite", (need,), (question,), (f"sq-{need}",),
    )


def test_canonical_mismatch_preserves_only_design_grounded_scoped_relations():
    design = _resolved_design()
    subject = design.research_subject

    assert subject.canonical_label == "Consumer financial wellbeing"
    assert subject.provenance["resolver"] == "brief_market_planner_mismatch_scoped"
    assert {row.label for row in subject.lexical_representations} == {
        "Consumer financial wellbeing", "consumer financial wellbeing",
    }
    assert {relation.relation_id for relation in subject.supporting_relations} == {
        "earnings", "prices", "labour",
    }
    earnings = next(x for x in subject.supporting_relations if x.relation_id == "earnings")
    assert earnings.information_need_refs == ("in-a",)
    assert earnings.research_question_refs == ("rq-a",)
    assert earnings.required_aspect_refs == ("real_earnings",)


def test_scoped_relation_changes_fingerprint_and_round_trips():
    subject = _resolved_design().research_subject
    reduced = replace(
        subject,
        supporting_relations=subject.supporting_relations[:-1],
        semantic_fingerprint="",
    )
    assert reduced.semantic_fingerprint != subject.semantic_fingerprint
    assert type(subject).from_dict(subject.to_dict()) == subject


@pytest.mark.parametrize(("text", "need", "question"), (
    ("Real earnings declined during the period.", "in-a", "rq-a"),
    ("Consumer price growth accelerated during the period.", "in-b", "rq-b"),
    ("Unemployment increased during the period.", "in-c", "rq-c"),
))
def test_relation_and_exact_required_aspect_form_positive_evidence_path(
    text, need, question,
):
    result = validate_candidate_provenance(
        _candidate(text, need),
        design=_resolved_design(),
        run_context=_context(need, question),
    )
    assert result.information_need_refs == (need,)
    assert result.metadata["_research_subject_audit"]["supporting_relation_id"]


def test_relation_scoped_to_other_need_remains_fail_closed():
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        validate_candidate_provenance(
            _candidate("Real earnings declined during the period.", "in-b"),
            design=_resolved_design(),
            run_context=_context("in-b", "rq-b"),
        )


def test_aspect_scoped_to_other_need_does_not_supply_local_relevance():
    design = _resolved_design()
    with pytest.raises(InvalidProvenanceError, match="local information-need relevance"):
        validate_candidate_provenance(
            _candidate(
                "Consumer financial wellbeing: real earnings declined during the period.",
                "in-b",
            ),
            design=design,
            run_context=_context("in-b", "rq-b"),
        )


def test_unapproved_lexical_synonym_and_source_only_context_do_not_qualify():
    design = _resolved_design()
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        validate_candidate_provenance(
            _candidate("Salary momentum weakened during the period.", "in-a"),
            design=design,
            run_context=_context("in-a", "rq-a"),
        )
