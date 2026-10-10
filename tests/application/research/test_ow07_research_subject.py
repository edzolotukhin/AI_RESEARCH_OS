from dataclasses import replace

import pytest

from application.evidence.provenance_validation import (
    InvalidProvenanceError, validate_candidate_provenance,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.evidence.subject_relevance import (
    SUBJECT_RELEVANT, SUBJECT_UNRESOLVED, assess_subject_text,
)
from application.ports.evidence_ports import EvidenceCandidate
from application.research_quality.targeted_search_query_builder import TargetedSearchQueryBuilder
from application.research.subject_resolution import resolve_subject_proposal
from application.research.design_validator import validate_subject_for_approval
from application.sources.deterministic_source_relevance import (
    build_relevance_context, evaluate_candidate,
)
from application.sources.search_query_builder import SearchQueryBuilder
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.research_subject import (
    LexicalRepresentation, RepresentationApprovalStatus, ResearchSubject,
    SubjectResolutionStatus, SupportingRelation,
)
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.research_quality.gap_type import GapType
from domain.sources.source_candidate import SourceCandidate
from domain.research_brief import ResearchBrief


def representation(identity, language, label, concept="core", *, approved=True):
    return LexicalRepresentation(
        representation_id=identity, language=language, label=label,
        normalized_phrases=(label,), concept_refs=(concept,), provenance="fixture",
        approval_status=(RepresentationApprovalStatus.APPROVED if approved
                         else RepresentationApprovalStatus.PROPOSED),
    )


def subject(*, approved=True, status=SubjectResolutionStatus.RESOLVED):
    rows = (
        representation("uk", "uk", "преміальний корм для собак", approved=approved),
        representation("en", "en", "premium dog food", approved=approved),
        representation("pl", "pl", "karma premium dla psów", approved=approved),
        representation("sr", "sr", "премијум храна за псе", approved=approved),
    )
    relation = SupportingRelation(
        relation_id="pet-ownership", relation_type="population_context",
        information_need_refs=("in-size",), concepts=("pet-ownership",),
        lexical_representations=(
            representation("owners-en", "en", "dog ownership statistics", "pet-ownership", approved=approved),
        ), explanation="Dog ownership supports market sizing.",
    )
    trade = SupportingRelation(
        relation_id="imports", relation_type="trade_import_context",
        information_need_refs=("in-size",), concepts=("imports",),
        lexical_representations=(
            representation("imports-en", "en", "dog food import statistics", "imports", approved=approved),
        ), explanation="Imports support supply sizing.",
    )
    regulatory = SupportingRelation(
        relation_id="packaging", relation_type="regulatory_context",
        information_need_refs=("in-position",), concepts=("packaging",),
        lexical_representations=(
            representation("packaging-en", "en", "pet food packaging regulation", "packaging", approved=approved),
        ), explanation="Packaging rules support positioning constraints.",
    )
    return ResearchSubject(
        subject_id="subject-fixed", canonical_label="Преміальний корм для собак",
        canonical_language="uk", core_concepts=("core",), lexical_representations=rows,
        supporting_relations=(relation, trade, regulatory), exclusions=("fashion clothing",),
        resolution_status=status, provenance={"resolver": "fixture", "timestamp": "one"},
    )


def design(value=None):
    value = subject() if value is None else value
    return ResearchDesign(
        id="design", language="uk", research_subject=value,
        research_questions=(
            ResearchQuestion("rq-position", "Позиціонування преміального корму для собак"),
            ResearchQuestion("rq-size", "Розмір ринку преміального корму для собак"),
        ),
        information_needs=(
            InformationNeed("in-position", "rq-position", "Ціна, якість і позиціонування брендів корму",
                            geography="Україна", evidence_expectation=EvidenceExpectation(EvidenceNature.QUALITATIVE)),
            InformationNeed("in-size", "rq-size", "Кількість власників собак і розмір ринку",
                            geography="Україна", evidence_expectation=EvidenceExpectation(EvidenceNature.QUANTITATIVE)),
        ), source_strategy=("industry",), analysis_plan=("compare",),
        deliverable_plan=("report",),
    )


def candidate(text, need="in-position"):
    return EvidenceCandidate(
        statement=text, source_excerpt=text, evidence_type="direct_excerpt",
        research_question_refs=(), information_need_refs=(need,),
    )


def context(need="in-position"):
    rq = "rq-size" if need == "in-size" else "rq-position"
    return RunScopedSourceContext("run", "design", (need,), (rq,), (f"sq-{need}",))


def validate(text, need="in-position", value=None):
    return validate_candidate_provenance(
        candidate(text, need), design=design(value), run_context=context(need),
    )


def test_subject_round_trip_identity_and_unicode():
    value = subject()
    restored = ResearchSubject.from_dict(value.to_dict())
    assert restored == value
    assert restored.subject_id == "subject-fixed"
    assert restored.canonical_label == "Преміальний корм для собак"


def test_fingerprint_ignores_provenance_but_changes_with_semantics():
    value = subject()
    changed_provenance = replace(value, provenance={"timestamp": "two"}, semantic_fingerprint="")
    assert changed_provenance.semantic_fingerprint == value.semantic_fingerprint
    changed_semantics = replace(value, exclusions=("different exclusion",), semantic_fingerprint="")
    assert changed_semantics.semantic_fingerprint != value.semantic_fingerprint


def test_proposal_is_not_executable_until_approved():
    proposed = subject(approved=False)
    assert not proposed.executable
    approved = proposed.approve()
    assert approved.executable
    assert approved.subject_id == proposed.subject_id


def test_partially_resolved_core_subject_can_be_approved():
    proposed = replace(
        subject(approved=False),
        resolution_status=SubjectResolutionStatus.PARTIALLY_RESOLVED,
        semantic_fingerprint="",
    )
    assert proposed.approve().executable


def test_approved_subject_is_frozen_in_design_round_trip():
    approved = subject()
    restored = ResearchDesign.from_dict(design(approved).to_dict())
    assert restored.research_subject.subject_id == approved.subject_id
    assert restored.research_subject.semantic_fingerprint == approved.semantic_fingerprint


@pytest.mark.parametrize("text", (
    "Преміальний корм для собак має різні ціни та позиціонування брендів.",
    "Premium dog food has different prices and brand positioning for dog owners.",
    "Karma premium dla psów różni się ceną i pozycjonowaniem marek.",
    "Премијум храна за псе има различите цене и позиционирање брендова.",
))
def test_uk_subject_accepts_approved_multilingual_representations(text):
    result = validate(text)
    assert result.information_need_refs == ("in-position",)
    assert result.metadata["_research_subject_audit"]["subject_decision"] == SUBJECT_RELEVANT


def test_english_subject_accepts_ukrainian_source():
    value = replace(subject(), canonical_label="Premium dog food", canonical_language="en",
                    semantic_fingerprint="")
    result = validate("Преміальний корм для собак має різні ціни та позиціонування брендів.", value=value)
    assert result.information_need_refs == ("in-position",)


@pytest.mark.parametrize("text", (
    "Kasta продає fashion clothing: бренди одягу, стиль, ціна та знижки.",
    "Automotive brands compete on price, positioning, channels and consumer behavior.",
    "A SaaS brand uses price, marketplace channels and communication.",
))
def test_generic_cross_domain_material_cannot_be_evidence(text):
    with pytest.raises(InvalidProvenanceError, match="subject relevance"):
        validate(text)


def test_subject_match_does_not_replace_same_language_local_relevance():
    with pytest.raises(InvalidProvenanceError):
        validate("Преміальний корм для собак: загальний обсяг ринку становить 10 тонн.")


def test_supporting_relation_is_need_bound():
    assert validate("Dog ownership statistics count households with dogs.", "in-size")
    with pytest.raises(InvalidProvenanceError):
        validate("Dog ownership statistics count households with dogs.", "in-position")


@pytest.mark.parametrize(("text", "need"), (
    ("Dog food import statistics report imported volumes.", "in-size"),
    ("Pet food packaging regulation defines mandatory package labels.", "in-position"),
))
def test_trade_and_regulatory_supporting_relations_are_bounded(text, need):
    result = validate(text, need)
    assert result.metadata["_research_subject_audit"]["supporting_relation_id"]


def test_subject_relevant_candidate_is_explicit_in_ranking():
    d = design()
    need = d.information_needs[0]
    row = SourceCandidate("fixture", "https://example.test/pet-food", "Premium dog food",
                          "Premium dog food positioning and prices in Ukraine", "sq", 1)
    decision = evaluate_candidate(build_relevance_context(d, need), row)
    assert decision.subject_decision == SUBJECT_RELEVANT


def test_unresolved_subject_cannot_validate_evidence():
    unresolved = replace(subject(), resolution_status=SubjectResolutionStatus.UNRESOLVED,
                         semantic_fingerprint="")
    decision = assess_subject_text(subject=unresolved, statement="Premium dog food",
                                   excerpt="Premium dog food", information_need_id="in-position")
    assert decision.decision == SUBJECT_UNRESOLVED
    with pytest.raises(InvalidProvenanceError):
        validate("Premium dog food has different prices.", value=unresolved)


def test_initial_query_uses_frozen_subject_without_extra_queries():
    queries = SearchQueryBuilder().build_queries(design())
    assert len(queries) == 2
    assert "преміальний корм для собак" in queries[0].query_text.casefold()
    assert "преміальний корм для собак" in queries[0].provider_query_text.casefold()


def test_targeted_query_uses_frozen_subject_without_fanout():
    d = design()
    request = TargetedResearchRequest(
        workflow_run_id="run", research_design_id=d.id,
        research_question_id="rq-position", information_need_id="in-position",
        gap_types=(GapType.NO_EVIDENCE,), attempt=1,
    )
    queries = TargetedSearchQueryBuilder().build_queries(
        design=d, request=request, max_queries=1, max_results=5,
    )
    assert len(queries) == 1
    assert "преміальний корм для собак" in queries[0].provider_query_text.casefold()


def test_unapproved_or_unresolved_subject_query_fails_closed():
    with pytest.raises(ValueError, match="ResearchSubject"):
        SearchQueryBuilder().build_queries(design(subject(approved=False)))


def test_source_ranking_keeps_unresolved_explicit():
    d = design()
    need = d.information_needs[0]
    relevance = build_relevance_context(d, need)
    row = SourceCandidate("fixture", "https://example.test/fashion", "Kasta fashion",
                          "brand price marketplace communication", "sq", 1)
    decision = evaluate_candidate(relevance, row)
    assert decision.subject_decision == SUBJECT_UNRESOLVED
    assert decision.reason == "subject_unresolved_no_positive_signal"
    assert not decision.is_fetch_eligible


def test_ukrainian_inflection_matches_without_domain_specific_aliases():
    value = ResearchSubject(
        subject_id="uk-subject", canonical_label="Мінеральні добрива",
        canonical_language="uk", core_concepts=("core",),
        lexical_representations=(
            representation("uk-core", "uk", "мінеральні добрива"),
        ), resolution_status=SubjectResolutionStatus.RESOLVED,
    )
    decision = assess_subject_text(
        subject=value,
        statement="Попит на мінеральне добриво зріс.",
        excerpt="Продаж мінерального добрива зріс у регіонах.",
        information_need_id="in-position",
    )
    assert decision.decision == SUBJECT_RELEVANT


def test_inflected_ukrainian_source_and_evidence_share_subject_semantics():
    value = ResearchSubject(
        subject_id="rings", canonical_label="обручальні кільця",
        canonical_language="uk", core_concepts=("core",),
        lexical_representations=(
            representation("rings-uk", "uk", "обручальні кільця"),
        ), resolution_status=SubjectResolutionStatus.RESOLVED,
    )
    d = replace(design(), research_subject=value)
    need = d.information_needs[0]
    source = SourceCandidate(
        "fixture", "https://example.test/rings", "Тренди обручок",
        "Українські обручки: ціни, бренди та позиціонування", "sq", 1,
    )
    source_decision = evaluate_candidate(build_relevance_context(d, need), source)
    assert source_decision.subject_decision == SUBJECT_RELEVANT
    evidence_decision = assess_subject_text(
        subject=value,
        statement="Ціни на обручки залежать від матеріалу.",
        excerpt="Ціни на обручки залежать від матеріалу.",
        information_need_id=need.id,
    )
    assert evidence_decision.decision == SUBJECT_RELEVANT


def test_unresolved_candidate_without_positive_topic_signal_is_ineligible():
    d = design()
    need = d.information_needs[0]
    row = SourceCandidate(
        "fixture", "https://example.test/crypto", "Crypto token forecast",
        "Market price forecast and capitalization", "sq", 1,
    )
    decision = evaluate_candidate(build_relevance_context(d, need), row)
    assert decision.subject_decision == SUBJECT_UNRESOLVED
    assert not decision.is_fetch_eligible
    assert decision.reason == "subject_unresolved_no_positive_signal"


def test_unresolved_candidate_with_positive_topic_signal_keeps_bounded_fallback():
    d = design()
    need = d.information_needs[0]
    row = SourceCandidate(
        "fixture", "https://example.test/nutrition", "Позиціонування брендів корму",
        "Ціна, якість і позиціонування брендів корму в Україні", "sq", 1,
    )
    decision = evaluate_candidate(build_relevance_context(d, need), row)
    assert decision.subject_decision == SUBJECT_UNRESOLVED
    assert decision.is_fetch_eligible
    assert decision.reason == "subject_unresolved_bounded_fallback"


def test_legacy_design_parses_without_inventing_subject():
    payload = design().to_dict()
    payload.pop("research_subject")
    assert ResearchDesign.from_dict(payload).research_subject is None


def test_brief_market_is_canonical_and_planner_aliases_are_proposals():
    brief = ResearchBrief(
        title="Дослідження", business_question="Що визначає вибір?",
        market="Преміальний корм для собак", language="uk",
    )
    value = resolve_subject_proposal(brief, {
        "canonical_label": "Преміальний корм для собак",
        "canonical_language": "uk",
        "lexical_representations": [{"language": "en", "label": "premium dog food"}],
    })
    assert value.canonical_label == brief.market
    assert not value.executable
    assert value.approve().executable


def test_explicit_market_remains_authoritative_when_planner_label_differs():
    brief = ResearchBrief("Study", "Question", market="Premium dog food", language="en")
    value = resolve_subject_proposal(brief, {
        "canonical_label": "Automotive market", "canonical_language": "en",
        "lexical_representations": [{"language": "en", "label": "automotive market"}],
    })
    assert value.resolution_status is SubjectResolutionStatus.RESOLVED
    assert value.canonical_label == brief.market
    assert {item.label for item in value.lexical_representations} == {brief.market}
    validate_subject_for_approval(replace(design(), research_subject=value))


def test_ukrainian_market_brief_survives_inflected_planner_label_and_round_trip():
    brief = ResearchBrief(
        title="Обручальні кільця — Україна",
        business_question="Як запустити новий бренд на українському ринку?",
        geography=("Україна",),
        market="Ринок обручальних кілець в Україні",
        language="uk",
        context="Аналіз ключових гравців, асортименту, цін і споживчих вподобань.",
    )
    value = resolve_subject_proposal(brief, {
        "canonical_label": "Український ринок обручальних кілець",
        "canonical_language": "uk",
        "lexical_representations": [
            {"language": "uk", "label": "обручальні кільця в Україні"},
        ],
    })

    assert value.resolution_status is SubjectResolutionStatus.RESOLVED
    assert value.canonical_label == "Ринок обручальних кілець в Україні"
    assert ResearchSubject.from_dict(value.to_dict()) == value


def test_genuinely_insufficient_brief_remains_unresolved():
    value = resolve_subject_proposal(
        ResearchBrief(title="", business_question="", language="uk"),
        None,
    )

    assert value.resolution_status is SubjectResolutionStatus.UNRESOLVED
    with pytest.raises(Exception, match="Предмет дослідження"):
        validate_subject_for_approval(replace(design(), research_subject=value))


def test_subjectless_legacy_design_is_viewable_but_not_approvable():
    legacy = replace(design(), research_subject=None)
    assert ResearchDesign.from_dict(legacy.to_dict()).research_subject is None
    with pytest.raises(Exception, match="нову ревізію"):
        validate_subject_for_approval(legacy)
