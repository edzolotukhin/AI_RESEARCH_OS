"""P1-07.5.1 legacy aspect-ID contract hardening tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from application.exceptions.structured_output_error import StructuredOutputError
from application.research_quality.allowed_aspect_ids import resolve_allowed_aspect_ids
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.raw_semantic_decision_contract import (
    RawSemanticDecisionContractGate,
    evaluate_aspect_id_membership,
    render_allowed_aspect_contract,
)
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.common.exceptions import ValidationError
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    normalize_semantic_decision,
)
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    _build_user_payload,
    _system_prompt,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    SufficiencyStructuredOutputGenerator,
)


LIVE_LABELS = [
    "certifications",
    "consistency",
    "lead times",
    "payment terms",
    "vendor onboarding requirements",
]


def _valid_legacy_payload(*, supported=None, missing=None) -> dict[str, object]:
    return {
        "supported_aspects": supported if supported is not None else [LEGACY_NEED_ASPECT_ID],
        "missing_aspects": missing if missing is not None else [],
        "semantic_conflicts": [],
        "confidence": 0.9,
        "reason": "Evidence supports the information need.",
    }


def _legacy_need(**kwargs) -> InformationNeed:
    defaults = {
        "id": "IN10",
        "research_question_id": "RQ1",
        "description": (
            "Assess certifications, consistency, lead times, payment terms, "
            "and vendor onboarding requirements."
        ),
    }
    defaults.update(kwargs)
    return InformationNeed(**defaults)


def _expectation_need(
    *,
    required_aspects: tuple[str, ...],
) -> InformationNeed:
    return InformationNeed(
        id="IN10",
        research_question_id="RQ1",
        description="Vendor assessment criteria.",
        evidence_expectation=EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            required_aspects=required_aspects,
        ),
    )


def _signals(*, need_id: str = "IN10") -> DeterministicSufficiencySignals:
    return DeterministicSufficiencySignals(
        information_need_id=need_id,
        research_question_id="RQ1",
        evidence_count=3,
        independent_source_count=2,
        evidence_ids=("evidence-0", "evidence-1", "evidence-2"),
        source_ids=("source-0", "source-1"),
    )


def _sample_evidence() -> tuple[Evidence, ...]:
    return (
        Evidence(
            id="evidence-0",
            project_id="project-1",
            source_id="source-0",
            source_content_checksum="checksum-0",
            workflow_run_id="run-1",
            research_design_id="design-1",
            created_at="2026-01-01T00:00:00+00:00",
            statement="Payment terms must align to statutory limits.",
            source_excerpt="Align payment terms.",
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            research_question_refs=("RQ1",),
            information_need_refs=("IN10",),
        ),
    )


class AllowedAspectSourceTests(unittest.TestCase):
    def test_legacy_mode_resolves_legacy_need(self) -> None:
        need = _legacy_need()
        self.assertEqual(resolve_allowed_aspect_ids(need), (LEGACY_NEED_ASPECT_ID,))

    def test_expectation_mode_resolves_required_aspects(self) -> None:
        need = _expectation_need(
            required_aspects=("pricing", "availability", "buyer_requirements"),
        )
        self.assertEqual(
            resolve_allowed_aspect_ids(need),
            ("pricing", "availability", "buyer_requirements"),
        )


class CallScopedContractGateTests(unittest.TestCase):
    def test_a_legacy_canonical_supported_passes(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        self.assertTrue(gate.accepts(_valid_legacy_payload()))
        self.assertIsNone(gate.last_rejection_code)

    def test_b_legacy_canonical_missing_passes(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(supported=[], missing=[LEGACY_NEED_ASPECT_ID])
        self.assertTrue(gate.accepts(payload))

    def test_c_legacy_descriptive_supported_rejected(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(supported=["payment terms"])
        self.assertFalse(gate.accepts(payload))
        self.assertEqual(gate.last_rejection_code, "unknown_aspect_id")
        self.assertEqual(gate.last_unknown_aspect_ids, ("payment terms",))

    def test_d_legacy_descriptive_missing_rejected(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(supported=[], missing=["payment terms"])
        self.assertFalse(gate.accepts(payload))
        self.assertEqual(gate.last_rejection_code, "unknown_aspect_id")

    def test_e_live_five_label_shape_rejected(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(supported=LIVE_LABELS)
        self.assertFalse(gate.accepts(payload))
        self.assertEqual(gate.last_rejection_code, "unknown_aspect_id")
        self.assertEqual(gate.last_unknown_aspect_ids, tuple(LIVE_LABELS))

    def test_f_mixed_canonical_and_descriptive_rejected(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(
            supported=[LEGACY_NEED_ASPECT_ID, "payment terms"],
        )
        self.assertFalse(gate.accepts(payload))
        self.assertIn("payment terms", gate.last_unknown_aspect_ids)

    def test_g_expectation_backed_all_canonical_passes(self) -> None:
        allowed = ("pricing", "availability", "buyer_requirements")
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=allowed)
        payload = {
            "supported_aspects": ["pricing"],
            "missing_aspects": ["availability", "buyer_requirements"],
            "semantic_conflicts": [],
            "confidence": 0.7,
            "reason": "Partial support.",
        }
        self.assertTrue(gate.accepts(payload))

    def test_h_expectation_backed_unknown_rejected(self) -> None:
        allowed = ("pricing", "availability", "buyer_requirements")
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=allowed)
        payload = {
            "supported_aspects": ["pricing"],
            "missing_aspects": ["buyer requirements"],
            "semantic_conflicts": [],
            "confidence": 0.7,
            "reason": "Partial support.",
        }
        self.assertFalse(gate.accepts(payload))
        self.assertEqual(gate.last_unknown_aspect_ids, ("buyer requirements",))

    def test_j_supported_missing_overlap_still_rejected(self) -> None:
        gate = RawSemanticDecisionContractGate(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        payload = _valid_legacy_payload(
            supported=[LEGACY_NEED_ASPECT_ID],
            missing=[LEGACY_NEED_ASPECT_ID],
        )
        self.assertFalse(gate.accepts(payload))
        self.assertEqual(gate.last_rejection_code, "supported_missing_overlap")


class StructuredOutputRetryTests(unittest.TestCase):
    def test_k_unknown_id_then_corrected_retry_succeeds(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content=json.dumps(_valid_legacy_payload(supported=LIVE_LABELS)),
                finish_reason="stop",
            ),
            LLMResponse(
                content=json.dumps(_valid_legacy_payload()),
                finish_reason="stop",
            ),
        ]
        generator = SufficiencyStructuredOutputGenerator(
            llm_client=mock_llm,
            max_attempts=2,
        )
        payload = generator.generate(
            Prompt(system="System", user="User"),
            allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,),
        )
        self.assertEqual(payload["supported_aspects"], [LEGACY_NEED_ASPECT_ID])
        self.assertFalse(generator.attempt_history[0].success)
        self.assertEqual(
            generator.attempt_history[0].contract_rejection_code,
            "unknown_aspect_id",
        )
        self.assertEqual(generator.attempt_history[0].unknown_aspect_ids, tuple(LIVE_LABELS))
        self.assertTrue(generator.attempt_history[1].success)

    def test_l_retry_exhaustion_preserves_unknown_id_diagnostics(self) -> None:
        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_legacy_payload(supported=LIVE_LABELS)),
            finish_reason="stop",
        )
        generator = SufficiencyStructuredOutputGenerator(
            llm_client=mock_llm,
            max_attempts=2,
        )
        with self.assertRaises(StructuredOutputError):
            generator.generate(
                Prompt(system="System", user="User"),
                allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,),
            )
        self.assertEqual(len(generator.attempt_history), 2)
        self.assertEqual(
            generator.attempt_history[-1].contract_rejection_code,
            "unknown_aspect_id",
        )
        self.assertEqual(
            generator.attempt_history[-1].unknown_aspect_ids,
            tuple(LIVE_LABELS),
        )


class NormalizerDefenseInDepthTests(unittest.TestCase):
    def test_m_direct_normalizer_still_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            normalize_semantic_decision(
                raw=RawSemanticDecision(
                    supported_aspects=tuple(LIVE_LABELS),
                    reason="Bypassed contract.",
                ),
                evidence_expectation=None,
            )
        self.assertIn("unknown aspect identifiers", str(ctx.exception))


class PromptAlignmentTests(unittest.TestCase):
    def test_n_legacy_prompt_and_payload_include_allowed_ids(self) -> None:
        need = _legacy_need()
        allowed = resolve_allowed_aspect_ids(need)
        prompt = _system_prompt(allowed_aspect_ids=allowed)
        self.assertIn(LEGACY_NEED_ASPECT_ID, prompt)
        self.assertIn("Never invent aspect names", prompt)
        self.assertIn("descriptive labels", prompt)

        payload = json.loads(
            _build_user_payload(
                research_question=ResearchQuestion(
                    id="RQ1",
                    question="Vendor requirements?",
                    objective_refs=(),
                ),
                information_need=need,
                evidence=_sample_evidence(),
                deterministic_signals=_signals(),
                allowed_aspect_ids=allowed,
            ),
        )
        self.assertEqual(payload["allowed_aspect_ids"], [LEGACY_NEED_ASPECT_ID])
        self.assertIn("payment terms", payload["information_need"]["description"])

    def test_o_expectation_backed_payload_includes_canonical_ids(self) -> None:
        need = _expectation_need(
            required_aspects=("pricing", "availability", "buyer_requirements"),
        )
        allowed = resolve_allowed_aspect_ids(need)
        contract = render_allowed_aspect_contract(allowed_aspect_ids=allowed)
        self.assertIn("'pricing'", contract)
        self.assertIn("'buyer_requirements'", contract)


class AssessorIntegrationTests(unittest.TestCase):
    def test_live_shape_does_not_reach_domain_validation_error_on_first_attempt(self) -> None:
        from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
            LlmSemanticSufficiencyAssessor,
        )

        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content=json.dumps(_valid_legacy_payload(supported=LIVE_LABELS)),
                finish_reason="stop",
            ),
            LLMResponse(
                content=json.dumps(_valid_legacy_payload()),
                finish_reason="stop",
            ),
        ]
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            structured_output_max_attempts=2,
        )
        assessment = assessor.assess(
            research_question=ResearchQuestion(
                id="RQ1",
                question="Vendor requirements?",
                objective_refs=(),
            ),
            information_need=_legacy_need(),
            evidence=_sample_evidence(),
            deterministic_signals=_signals(),
        )
        self.assertEqual(assessment.status.value, "sufficient")
        self.assertEqual(mock_llm.generate.call_count, 2)

    def test_exhausted_unknown_ids_raise_structured_output_error_with_diagnostics(self) -> None:
        from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
            LlmSemanticSufficiencyAssessor,
        )

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(_valid_legacy_payload(supported=LIVE_LABELS)),
            finish_reason="stop",
        )
        assessor = LlmSemanticSufficiencyAssessor(
            llm_client=mock_llm,
            structured_output_max_attempts=1,
        )
        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            assessor.assess(
                research_question=ResearchQuestion(
                    id="RQ1",
                    question="Vendor requirements?",
                    objective_refs=(),
                ),
                information_need=_legacy_need(),
                evidence=_sample_evidence(),
                deterministic_signals=_signals(),
            )
        diagnostics = ctx.exception.diagnostics
        assert diagnostics is not None
        self.assertEqual(diagnostics.information_need_id, "IN10")
        self.assertEqual(diagnostics.allowed_aspect_ids, (LEGACY_NEED_ASPECT_ID,))
        self.assertEqual(diagnostics.contract_rejection_code, "unknown_aspect_id")
        self.assertEqual(diagnostics.unknown_aspect_ids, tuple(LIVE_LABELS))


if __name__ == "__main__":
    unittest.main()
