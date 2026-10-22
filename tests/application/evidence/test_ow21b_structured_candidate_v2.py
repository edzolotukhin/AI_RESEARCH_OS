from dataclasses import replace
from functools import lru_cache
import json
from unittest.mock import Mock

import pytest

from application.evidence.provenance_validation import (
    InvalidProvenanceError,
    validate_candidate_provenance,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.evidence.semantic_assignment import (
    CONTRACT_VERSION,
    required_aspect_refs,
    semantic_assignment,
)
from application.research_scope.authoritative_scope import SCOPE_KEY, SCOPE_VERSION
from application.ports.evidence_ports import EvidenceCandidate
from application.research.subject_resolution import resolve_subject_proposal
from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor


@lru_cache(maxsize=1)
def _design() -> ResearchDesign:
    base = ResearchDesign(
        id="ow21b",
        language="uk",
        research_questions=(
            ResearchQuestion("rq-income", "Як змінилися доходи та зарплати працівників?"),
            ResearchQuestion("rq-prices", "Як змінилися споживчі ціни домогосподарств?"),
        ),
        information_needs=(
            InformationNeed(
                "in-income",
                "rq-income",
                "Встановити динаміку доходів і реальної заробітної плати працівників",
                geography="Україна",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("доходи", "реальна_заробітна_плата"),
                    geography="Україна",
                ),
            ),
            InformationNeed(
                "in-prices",
                "rq-prices",
                "Встановити динаміку споживчих цін домогосподарств",
                geography="Україна",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("споживчі_ціни",),
                    geography="Україна",
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
        "supporting_relations": [
            {
                "relation_id": "income-context",
                "relation_type": "economic_context",
                "information_need_refs": ["in-income"],
                "research_question_refs": ["rq-income"],
                "required_aspect_refs": ["доходи", "реальна_заробітна_плата"],
                "concepts": ["income-context"],
                "lexical_representations": [
                    {
                        "representation_id": "income-context-uk",
                        "language": "uk",
                        "label": "фінансова стійкість",
                        "normalized_phrases": ["фінансова стійкість"],
                        "concept_refs": ["income-context"],
                    },
                ],
                "explanation": "Контекст доходів працівників",
            },
        ],
        "exclusions": ["криптовалютні активи"],
    }
    subject = resolve_subject_proposal(
        ResearchBrief(
            title="Добробут",
            business_question="Як змінився добробут?",
            market="Добробут домогосподарств",
            language="uk",
        ),
        proposal,
        design=base,
    ).approve()
    return replace(base, research_subject=subject)


def _candidate(
    *,
    statement: str = "Реальна заробітна плата працівників зросла на 8 відсотків.",
    excerpt: str | None = None,
    need_id: str = "in-income",
    aspects: tuple[str, ...] = ("реальна_заробітна_плата",),
    binding_type: str = "supporting_relation",
    relation_id: str | None = "income-context",
    subject_id: str | None = None,
    subject_fingerprint: str | None = None,
) -> EvidenceCandidate:
    design = _design()
    subject = design.research_subject
    assert subject is not None
    binding = {
        "binding_type": binding_type,
        "subject_id": subject_id or subject.subject_id,
        "subject_fingerprint": subject_fingerprint or subject.semantic_fingerprint,
    }
    if relation_id is not None:
        binding["supporting_relation_id"] = relation_id
    return EvidenceCandidate(
        statement=statement,
        source_excerpt=excerpt if excerpt is not None else statement,
        evidence_type="direct_excerpt",
        research_question_refs=(),
        information_need_refs=(need_id,),
        confidence=0.8,
        metadata={"observation_period": "2025"},
        contract_version=CONTRACT_VERSION,
        required_aspect_refs=aspects,
        subject_binding=binding,
        semantic_justification="The excerpt directly supports this scoped assignment.",
        geography_applicability=("Україна",),
    )


def _validate(candidate: EvidenceCandidate, *, design: ResearchDesign | None = None):
    design = design or _design()
    need_id = candidate.information_need_refs[0]
    question_id = "rq-prices" if need_id == "in-prices" else "rq-income"
    return validate_candidate_provenance(
        candidate,
        design=design,
        run_context=RunScopedSourceContext(
            "run", design.id, (need_id,), (question_id,), ("sq",),
        ),
    )


def _source() -> Source:
    return Source(
        id="source",
        project_id="project",
        url="https://example.com/source",
        canonical_url="https://example.com/source",
        title="Official compensation statistics",
        retrieved_at="2026-10-17T00:00:00Z",
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text="Employee compensation increased by 8 percent.",
        content_checksum="checksum",
    )


def _extractor(content: str):
    client = Mock()
    client.generate.return_value = LLMResponse(content=content)
    return LlmEvidenceExtractor(llm_client=client), client


def test_extractor_receives_closed_run_pinned_vocabulary():
    extractor, client = _extractor('{"items":[]}')
    extractor.extract(
        source=_source(),
        design=_design(),
        run_context=RunScopedSourceContext(
            "run", "ow21b", ("in-income",), ("rq-income",), ("sq",),
        ),
    )
    prompt = client.generate.call_args.args[0]
    subject = _design().research_subject
    assert subject is not None
    assert subject.subject_id in prompt.user
    assert subject.semantic_fingerprint in prompt.user
    assert "income-context" in prompt.user
    assert "реальна_заробітна_плата" in prompt.user
    assert "Україна" in prompt.user
    assert CONTRACT_VERSION in prompt.system


def test_extractor_parses_v2_assignment_fields_without_inventing_ids():
    subject = _design().research_subject
    assert subject is not None
    payload = {
        "items": [{
            "contract_version": CONTRACT_VERSION,
            "statement": "Employee compensation increased by 8 percent.",
            "source_excerpt": "Employee compensation increased by 8 percent.",
            "information_need_id": "in-income",
            "required_aspect_refs": ["реальна_заробітна_плата"],
            "subject_binding": {
                "binding_type": "supporting_relation",
                "subject_id": subject.subject_id,
                "subject_fingerprint": subject.semantic_fingerprint,
                "supporting_relation_id": "income-context",
            },
            "semantic_justification": "The excerpt directly supports the assignment.",
            "geography_applicability": ["Україна"],
            "evidence_type": "direct_excerpt",
            "direct": True,
            "confidence": 0.8,
        }],
    }
    extractor, _ = _extractor(json.dumps(payload, ensure_ascii=False))
    candidates = extractor.extract(
        source=_source(),
        design=_design(),
        run_context=RunScopedSourceContext(
            "run", "ow21b", ("in-income",), ("rq-income",), ("sq",),
        ),
    )
    assert len(candidates) == 1
    assert candidates[0].contract_version == CONTRACT_VERSION
    assert candidates[0].required_aspect_refs == ("реальна_заробітна_плата",)
    assert candidates[0].subject_binding["supporting_relation_id"] == "income-context"


def test_grounded_canonical_v2_candidate_is_accepted():
    candidate = _candidate(
        statement="Добробут домогосподарств зріс на 8 відсотків.",
        binding_type="canonical_subject",
        relation_id=None,
    )
    result = _validate(candidate)
    assert result.information_need_refs == ("in-income",)
    assert semantic_assignment(result.metadata)["binding_type"] == "canonical_subject"
    assert result.metadata[SCOPE_KEY]["version"] == SCOPE_VERSION
    assert result.metadata[SCOPE_KEY]["geography"] == ["україна"]


@pytest.mark.parametrize(
    "text",
    (
        "Оплата праці штатних працівників збільшилася на 8 відсотків.",
        "Employee compensation increased by 8 percent.",
    ),
)
def test_structurally_valid_paraphrase_without_subject_phrase_is_accepted(text):
    result = _validate(_candidate(statement=text))
    assignment = semantic_assignment(result.metadata)
    assert assignment is not None
    assert assignment["binding_type"] == "supporting_relation"


def test_stale_or_invented_information_need_is_rejected():
    with pytest.raises(InvalidProvenanceError, match="not in the run design"):
        _validate(_candidate(need_id="invented-in"))


def test_aspect_from_another_information_need_is_rejected():
    with pytest.raises(InvalidProvenanceError, match="outside the assigned information need"):
        _validate(_candidate(aspects=("споживчі_ціни",)))


def test_invalid_relation_scope_is_rejected():
    with pytest.raises(InvalidProvenanceError, match="outside the assigned information need"):
        _validate(
            _candidate(
                need_id="in-prices",
                aspects=("споживчі_ціни",),
            ),
        )


def test_excerpt_that_does_not_support_statement_is_rejected():
    with pytest.raises(InvalidProvenanceError, match="unsupported by its grounded excerpt"):
        _validate(
            _candidate(
                statement="Реальна заробітна плата працівників зросла.",
                excerpt="Споживчі ціни домогосподарств знизилися.",
            ),
        )


def test_subject_exclusion_remains_fail_closed():
    with pytest.raises(InvalidProvenanceError, match="explicit ResearchSubject exclusion"):
        _validate(_candidate(statement="Криптовалютні активи зросли на 8 відсотків."))


def test_zero_aspect_contextual_evidence_is_accepted_with_zero_coverage():
    result = _validate(_candidate(aspects=()))
    assert required_aspect_refs(result.metadata) == ()


def test_multiple_valid_aspects_are_persisted_in_assignment():
    result = _validate(_candidate(aspects=("доходи", "реальна_заробітна_плата")))
    assert required_aspect_refs(result.metadata) == (
        "доходи", "реальна_заробітна_плата",
    )


@pytest.mark.parametrize("field", ("subject_id", "subject_fingerprint"))
def test_stale_subject_identity_or_fingerprint_is_rejected(field):
    values = {field: "stale-value"}
    with pytest.raises(InvalidProvenanceError, match="stale or unknown ResearchSubject"):
        _validate(_candidate(**values))


def test_lexical_diagnostic_failure_is_non_blocking_for_v2():
    result = _validate(
        _candidate(statement="Employee compensation increased by 8 percent."),
    )
    assignment = semantic_assignment(result.metadata)
    assert assignment is not None
    assert assignment["lexical_diagnostics"]["subject_decision"] != "subject_relevant"


def test_legacy_candidate_keeps_existing_lexical_rejection():
    legacy = EvidenceCandidate(
        statement="Продаж автомобілів преміумкласу збільшився.",
        source_excerpt="Продаж автомобілів преміумкласу збільшився.",
        evidence_type="direct_excerpt",
        research_question_refs=(),
        information_need_refs=("in-income",),
    )
    with pytest.raises(InvalidProvenanceError, match="subject continuity"):
        _validate(legacy)


def test_semantic_assignment_metadata_round_trips_with_evidence():
    validated = _validate(_candidate(aspects=("доходи",)))
    evidence = Evidence(
        id="evidence",
        project_id="project",
        source_id="source",
        source_content_checksum="checksum",
        workflow_run_id="run",
        research_design_id="ow21b",
        statement=validated.statement,
        source_excerpt=validated.source_excerpt,
        created_at="2026-10-17T00:00:00Z",
        evidence_type=EvidenceType.DIRECT_EXCERPT,
        metadata=dict(validated.metadata or {}),
    )
    restored = Evidence.from_dict(evidence.to_dict())
    assert semantic_assignment(restored) == semantic_assignment(evidence)
    assert required_aspect_refs(restored) == ("доходи",)


def test_duplicate_aspect_refs_are_rejected():
    with pytest.raises(InvalidProvenanceError, match="duplicate or excessive"):
        _validate(_candidate(aspects=("доходи", "доходи")))


def test_more_than_eight_aspect_refs_are_rejected_before_scope_acceptance():
    aspects = tuple(f"aspect_{index}" for index in range(9))
    with pytest.raises(InvalidProvenanceError, match="duplicate or excessive"):
        _validate(_candidate(aspects=aspects))
