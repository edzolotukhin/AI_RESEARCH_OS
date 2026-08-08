"""P1-07.5 offline forensic tests for Semantic Sufficiency aspect-ID contract."""

from __future__ import annotations

import json
import unittest

from application.research_quality.raw_semantic_decision_contract import (
    evaluate_raw_semantic_decision_payload,
    raw_semantic_decision_output_instructions,
    raw_semantic_decision_payload_contract,
)
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.semantic_sufficiency_adapter import (
    semantic_assessment_from_raw_decision,
)
from domain.common.exceptions import ValidationError
from domain.evidence.evidence_type import EvidenceType
from domain.evidence.evidence import Evidence
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    legacy_required_aspects,
    normalize_semantic_decision,
)
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    _build_user_payload,
    _system_prompt,
)


def _signals(*, need_id: str = "IN10", evidence_count: int = 3) -> DeterministicSufficiencySignals:
    return DeterministicSufficiencySignals(
        information_need_id=need_id,
        research_question_id="RQ1",
        evidence_count=evidence_count,
        independent_source_count=evidence_count,
        evidence_ids=tuple(f"evidence-{index}" for index in range(evidence_count)),
        source_ids=tuple(f"source-{index}" for index in range(evidence_count)),
    )


def _legacy_need(*, description: str = "Vendor onboarding requirements and payment terms.") -> InformationNeed:
    return InformationNeed(
        id="IN10",
        research_question_id="RQ1",
        description=description,
    )


def _expectation_need(
    *,
    required_aspects: tuple[str, ...],
    description: str = "Vendor assessment criteria.",
) -> InformationNeed:
    return InformationNeed(
        id="IN10",
        research_question_id="RQ1",
        description=description,
        evidence_expectation=EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            required_aspects=required_aspects,
        ),
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


class SemanticAspectIdContractForensicsTests(unittest.TestCase):
    def test_a_canonical_id_passes_contract_and_normalizer(self) -> None:
        payload = {
            "supported_aspects": ["payment_terms"],
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.9,
            "reason": "Supported.",
        }
        need = _expectation_need(required_aspects=("payment_terms", "certifications"))
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        normalized = normalize_semantic_decision(
            raw=RawSemanticDecision.from_dict(payload),
            evidence_expectation=need.evidence_expectation,
        )
        self.assertIn("payment_terms", normalized.supported_aspects)

    def test_b_unknown_descriptive_label_passes_contract_fails_normalizer(self) -> None:
        payload = {
            "supported_aspects": ["payment terms"],
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.9,
            "reason": "Supported.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        with self.assertRaises(ValidationError) as ctx:
            normalize_semantic_decision(
                raw=RawSemanticDecision.from_dict(payload),
                evidence_expectation=None,
            )
        self.assertIn("unknown aspect identifiers", str(ctx.exception))
        self.assertIn("payment terms", str(ctx.exception))

    def test_c_description_like_label_not_canonical_id_fails_normalizer(self) -> None:
        need = _expectation_need(
            required_aspects=("payment_terms", "vendor_onboarding_requirements"),
            description="Assess payment terms and vendor onboarding requirements.",
        )
        payload = {
            "supported_aspects": ["payment terms", "vendor onboarding requirements"],
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.8,
            "reason": "Partial support.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        with self.assertRaises(ValidationError):
            normalize_semantic_decision(
                raw=RawSemanticDecision.from_dict(payload),
                evidence_expectation=need.evidence_expectation,
            )

    def test_d_mixed_canonical_and_descriptive_fails_normalizer(self) -> None:
        need = _expectation_need(required_aspects=("payment_terms", "certifications"))
        payload = {
            "supported_aspects": ["payment_terms", "payment terms"],
            "missing_aspects": ["certifications"],
            "semantic_conflicts": [],
            "confidence": 0.7,
            "reason": "Mixed labels.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        with self.assertRaises(ValidationError) as ctx:
            normalize_semantic_decision(
                raw=RawSemanticDecision.from_dict(payload),
                evidence_expectation=need.evidence_expectation,
            )
        self.assertIn("payment terms", str(ctx.exception))

    def test_e_duplicate_ids_deduped_in_normalizer(self) -> None:
        raw = RawSemanticDecision(
            supported_aspects=("payment_terms", "payment_terms"),
            missing_aspects=(),
            reason="Duplicate supported ids.",
        )
        normalized = normalize_semantic_decision(
            raw=raw,
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.QUALITATIVE,
                required_aspects=("payment_terms",),
            ),
        )
        self.assertEqual(normalized.supported_aspects, ("payment_terms",))

    def test_f_supported_missing_overlap_rejected_by_contract(self) -> None:
        payload = {
            "supported_aspects": ["payment_terms"],
            "missing_aspects": ["payment_terms"],
            "semantic_conflicts": [],
            "confidence": 0.5,
            "reason": "Overlap.",
        }
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "supported_missing_overlap",
        )

    def test_g_legacy_path_requires_legacy_need_id(self) -> None:
        self.assertEqual(legacy_required_aspects(), (LEGACY_NEED_ASPECT_ID,))
        payload = {
            "supported_aspects": [
                "certifications",
                "consistency",
                "lead times",
                "payment terms",
                "vendor onboarding requirements",
            ],
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.9,
            "reason": "Live-like invented aspects.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        with self.assertRaises(SemanticSufficiencyAssessmentError) as ctx:
            semantic_assessment_from_raw_decision(
                information_need=_legacy_need(),
                signals=_signals(),
                raw_semantic=RawSemanticDecision.from_dict(payload),
            )
        message = str(ctx.exception)
        for label in (
            "certifications",
            "consistency",
            "lead times",
            "payment terms",
            "vendor onboarding requirements",
        ):
            self.assertIn(label, message)

    def test_h_expectation_backed_multi_aspect_path(self) -> None:
        need = _expectation_need(
            required_aspects=(
                "certifications",
                "consistency",
                "lead_times",
                "payment_terms",
                "vendor_onboarding_requirements",
            ),
        )
        payload = {
            "supported_aspects": ["payment_terms"],
            "missing_aspects": [
                "certifications",
                "consistency",
                "lead_times",
                "vendor_onboarding_requirements",
            ],
            "semantic_conflicts": [],
            "confidence": 0.6,
            "reason": "Partial.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))
        assessment = semantic_assessment_from_raw_decision(
            information_need=need,
            signals=_signals(),
            raw_semantic=RawSemanticDecision.from_dict(payload),
        )
        self.assertEqual(
            assessment.missing_aspects,
            tuple(payload["missing_aspects"]),
        )

    def test_i_prompt_includes_legacy_canonical_id(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn(LEGACY_NEED_ASPECT_ID, instructions)
        self.assertIn("Do not invent additional aspect identifiers", instructions)

    def test_j_user_payload_includes_description_not_allowed_id_list(self) -> None:
        need = _legacy_need(
            description=(
                "Assess certifications, consistency, lead times, payment terms, "
                "and vendor onboarding requirements."
            ),
        )
        question = ResearchQuestion(
            id="RQ1",
            question="What are vendor requirements?",
            objective_refs=(),
        )
        payload = json.loads(
            _build_user_payload(
                research_question=question,
                information_need=need,
                evidence=_sample_evidence(),
                deterministic_signals=_signals(),
                allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,),
            ),
        )
        self.assertIn("Assess certifications", payload["information_need"]["description"])
        self.assertNotIn("evidence_expectation", payload["information_need"])
        self.assertIn("allowed_aspect_ids", payload)
        self.assertEqual(payload["allowed_aspect_ids"], [LEGACY_NEED_ASPECT_ID])
        self.assertIn("payment terms", payload["information_need"]["description"])
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, payload["information_need"]["description"])

    def test_live_like_assessment_order_in10_before_in6_in8(self) -> None:
        need_ids = ("IN10", "IN6", "IN8")
        self.assertEqual(
            sorted(need_ids, key=lambda item: ("RQ1", item)),
            ["IN10", "IN6", "IN8"],
        )

    def test_system_prompt_does_not_enumerate_allowed_ids_in_user_payload(self) -> None:
        prompt = _system_prompt(allowed_aspect_ids=(LEGACY_NEED_ASPECT_ID,))
        self.assertIn("Legacy InformationNeed (evidence_expectation absent)", prompt)
        self.assertIn("EvidenceExpectation present", prompt)


class LiveRunReconstructionForensicsTests(unittest.TestCase):
    def test_descriptive_labels_pass_structured_output_only(self) -> None:
        """Reproduce live failure class: contract pass, normalizer fail."""
        live_labels = [
            "certifications",
            "consistency",
            "lead times",
            "payment terms",
            "vendor onboarding requirements",
        ]
        payload = {
            "supported_aspects": live_labels,
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.85,
            "reason": "Evidence supports procurement dimensions.",
        }
        self.assertTrue(raw_semantic_decision_payload_contract(payload))
        with self.assertRaises(ValidationError):
            normalize_semantic_decision(
                raw=RawSemanticDecision.from_dict(payload),
                evidence_expectation=None,
            )


if __name__ == "__main__":
    unittest.main()
