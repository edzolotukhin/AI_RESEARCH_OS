"""P1-06 M1/M2 semantic sufficiency contract foundation tests."""

from __future__ import annotations

import ast
import dataclasses
import json
import unittest
from pathlib import Path

from domain.common.exceptions import ValidationError
from domain.planning.aspect_identifiers import canonical_aspect_ids
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.policy_sufficiency_status import (
    derive_policy_sufficiency_status,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_aspect_validation import aspect_sets_for_policy
from domain.research_quality.sufficiency_policy_result import SufficiencyPolicyResult
from domain.research_quality.sufficiency_status import SufficiencyStatus

from tests.fixtures.planner_responses import VALID_RESEARCH_DESIGN_RESPONSE

REPO_ROOT = Path(__file__).resolve().parents[3]


def _quantitative_expectation(**overrides: object) -> EvidenceExpectation:
    base = {
        "nature": EvidenceNature.QUANTITATIVE,
        "required_aspects": (
            "market_size_value",
            "market_size_basis",
            "market_size_geography",
        ),
        "geography": "Serbia",
        "timeframe": "current",
        "minimum_independent_sources": 2,
        "requires_quantitative_evidence": True,
    }
    base.update(overrides)
    return EvidenceExpectation(**base)  # type: ignore[arg-type]


class EvidenceNatureTests(unittest.TestCase):
    def test_quantitative_valid(self) -> None:
        self.assertEqual(EvidenceNature.QUANTITATIVE.value, "quantitative")

    def test_qualitative_valid(self) -> None:
        self.assertEqual(EvidenceNature.QUALITATIVE.value, "qualitative")

    def test_mixed_valid(self) -> None:
        self.assertEqual(EvidenceNature.MIXED.value, "mixed")

    def test_deterministic_serialization_representation(self) -> None:
        payload = {"nature": EvidenceNature.MIXED.value}
        restored = EvidenceExpectation.from_dict(
            {
                **payload,
                "required_aspects": ("aspect_a",),
            },
        )
        self.assertEqual(restored.nature, EvidenceNature.MIXED)
        self.assertEqual(restored.to_dict()["nature"], "mixed")


class EvidenceExpectationTests(unittest.TestCase):
    def test_valid_quantitative_expectation(self) -> None:
        expectation = _quantitative_expectation()
        self.assertEqual(expectation.nature, EvidenceNature.QUANTITATIVE)
        self.assertTrue(expectation.requires_quantitative_evidence)

    def test_valid_qualitative_expectation(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            required_aspects=("brand_perception_summary",),
            requires_quantitative_evidence=False,
        )
        self.assertEqual(expectation.nature, EvidenceNature.QUALITATIVE)

    def test_valid_mixed_expectation(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.MIXED,
            required_aspects=("market_trend_direction", "market_trend_magnitude"),
        )
        self.assertEqual(expectation.nature, EvidenceNature.MIXED)

    def test_required_aspects_normalize_deterministically(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUANTITATIVE,
            required_aspects=("  aspect_a  ", "aspect_b", "aspect_a"),
        )
        self.assertEqual(expectation.required_aspects, ("aspect_a", "aspect_b"))

    def test_canonical_aspect_ids_remain_unchanged_through_roundtrip(self) -> None:
        aspects = (
            "market_size_value",
            "market_size_basis",
            "market_size_geography",
            "market_size_timeframe",
        )
        original = EvidenceExpectation(
            nature=EvidenceNature.QUANTITATIVE,
            required_aspects=aspects,
        )
        restored = EvidenceExpectation.from_dict(original.to_dict())
        self.assertEqual(restored.required_aspects, aspects)

    def test_blank_required_aspect_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE,
                required_aspects=("",),
            )

    def test_whitespace_only_required_aspect_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE,
                required_aspects=("   ",),
            )

    def test_duplicate_aspect_behavior_deterministic(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUANTITATIVE,
            required_aspects=("aspect_a", "aspect_b", "aspect_a"),
        )
        self.assertEqual(expectation.required_aspects, ("aspect_a", "aspect_b"))

    def test_minimum_independent_sources_none_accepted(self) -> None:
        expectation = EvidenceExpectation(nature=EvidenceNature.QUALITATIVE)
        self.assertIsNone(expectation.minimum_independent_sources)

    def test_minimum_independent_sources_one_accepted(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            minimum_independent_sources=1,
        )
        self.assertEqual(expectation.minimum_independent_sources, 1)

    def test_minimum_independent_sources_greater_than_one_accepted(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            minimum_independent_sources=3,
        )
        self.assertEqual(expectation.minimum_independent_sources, 3)

    def test_minimum_independent_sources_zero_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceExpectation(
                nature=EvidenceNature.QUALITATIVE,
                minimum_independent_sources=0,
            )

    def test_negative_minimum_independent_sources_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceExpectation(
                nature=EvidenceNature.QUALITATIVE,
                minimum_independent_sources=-1,
            )

    def test_geography_none_accepted(self) -> None:
        expectation = EvidenceExpectation(nature=EvidenceNature.QUALITATIVE)
        self.assertIsNone(expectation.geography)

    def test_timeframe_none_accepted(self) -> None:
        expectation = EvidenceExpectation(nature=EvidenceNature.QUALITATIVE)
        self.assertIsNone(expectation.timeframe)

    def test_deterministic_geography_normalization(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            geography="  Serbia  ",
        )
        self.assertEqual(expectation.geography, "Serbia")
        blank = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            geography="   ",
        )
        self.assertIsNone(blank.geography)

    def test_deterministic_timeframe_normalization(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUALITATIVE,
            timeframe="  current  ",
        )
        self.assertEqual(expectation.timeframe, "current")

    def test_requires_quantitative_evidence_bool_validation(self) -> None:
        with self.assertRaises(ValidationError):
            EvidenceExpectation(
                nature=EvidenceNature.QUANTITATIVE,
                requires_quantitative_evidence="yes",  # type: ignore[arg-type]
            )

    def test_to_dict_deterministic(self) -> None:
        expectation = _quantitative_expectation()
        first = json.dumps(expectation.to_dict(), sort_keys=True)
        second = json.dumps(expectation.to_dict(), sort_keys=True)
        self.assertEqual(first, second)

    def test_from_dict_works(self) -> None:
        payload = _quantitative_expectation().to_dict()
        restored = EvidenceExpectation.from_dict(payload)
        self.assertEqual(restored.nature, EvidenceNature.QUANTITATIVE)

    def test_object_dict_object_stable(self) -> None:
        original = _quantitative_expectation()
        restored = EvidenceExpectation.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_dict_object_dict_stable(self) -> None:
        payload = _quantitative_expectation().to_dict()
        restored = EvidenceExpectation.from_dict(payload).to_dict()
        self.assertEqual(restored, payload)


class RawSemanticDecisionTests(unittest.TestCase):
    def test_valid_raw_semantic_decision(self) -> None:
        decision = RawSemanticDecision(
            supported_aspects=("market_size_value",),
            missing_aspects=("market_size_basis",),
            semantic_conflicts=("market_size_geography",),
            confidence=0.75,
            reason="Partial quantitative coverage.",
        )
        self.assertEqual(decision.confidence, 0.75)

    def test_confidence_zero_accepted(self) -> None:
        decision = RawSemanticDecision(confidence=0.0)
        self.assertEqual(decision.confidence, 0.0)

    def test_confidence_one_accepted(self) -> None:
        decision = RawSemanticDecision(confidence=1.0)
        self.assertEqual(decision.confidence, 1.0)

    def test_confidence_below_zero_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RawSemanticDecision(confidence=-0.01)

    def test_confidence_above_one_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RawSemanticDecision(confidence=1.01)

    def test_supported_aspects_tuple_normalization(self) -> None:
        decision = RawSemanticDecision(
            supported_aspects=[" aspect_a ", "aspect_b", "aspect_a"],
        )
        self.assertEqual(decision.supported_aspects, ("aspect_a", "aspect_b"))

    def test_missing_aspects_tuple_normalization(self) -> None:
        decision = RawSemanticDecision(
            missing_aspects=[" aspect_x ", "aspect_y"],
        )
        self.assertEqual(decision.missing_aspects, ("aspect_x", "aspect_y"))

    def test_semantic_conflicts_tuple_normalization(self) -> None:
        decision = RawSemanticDecision(
            semantic_conflicts=[" conflict_a ", "conflict_a"],
        )
        self.assertEqual(decision.semantic_conflicts, ("conflict_a",))

    def test_blank_aspect_handling_deterministic(self) -> None:
        with self.assertRaises(ValidationError):
            RawSemanticDecision(supported_aspects=(" ",))

    def test_reason_normalization_deterministic(self) -> None:
        decision = RawSemanticDecision(reason="  semantic note  ")
        self.assertEqual(decision.reason, "semantic note")

    def test_contract_contains_no_status_field(self) -> None:
        self.assertNotIn("status", RawSemanticDecision.__dataclass_fields__)

    def test_contract_contains_no_gap_types_field(self) -> None:
        self.assertNotIn("gap_types", RawSemanticDecision.__dataclass_fields__)

    def test_contract_contains_no_blocking_field(self) -> None:
        self.assertNotIn("blocking", RawSemanticDecision.__dataclass_fields__)

    def test_contract_contains_no_ready_for_analysis_field(self) -> None:
        self.assertNotIn(
            "ready_for_analysis",
            RawSemanticDecision.__dataclass_fields__,
        )

    def test_contract_contains_no_search_directives_field(self) -> None:
        self.assertNotIn(
            "search_directives",
            RawSemanticDecision.__dataclass_fields__,
        )

    def test_contract_contains_no_coverage_field(self) -> None:
        self.assertNotIn("coverage", RawSemanticDecision.__dataclass_fields__)


class SufficiencyPolicyResultTests(unittest.TestCase):
    def test_valid_sufficiency_policy_result(self) -> None:
        result = SufficiencyPolicyResult(
            coverage=0.8,
            gap_types=(GapType.INSUFFICIENT_DEPTH,),
        )
        self.assertEqual(result.coverage, 0.8)

    def test_coverage_zero_accepted(self) -> None:
        result = SufficiencyPolicyResult(coverage=0.0)
        self.assertEqual(result.coverage, 0.0)

    def test_coverage_one_accepted(self) -> None:
        result = SufficiencyPolicyResult(coverage=1.0)
        self.assertEqual(result.coverage, 1.0)

    def test_coverage_below_zero_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SufficiencyPolicyResult(coverage=-0.01)

    def test_coverage_above_one_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SufficiencyPolicyResult(coverage=1.01)

    def test_gap_types_normalized_deterministically(self) -> None:
        result = SufficiencyPolicyResult(
            coverage=0.5,
            gap_types=[
                GapType.INSUFFICIENT_DEPTH,
                "insufficient_depth",
                GapType.STALE_EVIDENCE,
            ],
        )
        self.assertEqual(
            result.gap_types,
            (GapType.INSUFFICIENT_DEPTH, GapType.STALE_EVIDENCE),
        )

    def test_blocking_derived_correctly_from_blocking_gap_types(self) -> None:
        blocking_result = SufficiencyPolicyResult(
            coverage=0.5,
            gap_types=(GapType.INSUFFICIENT_DEPTH,),
        )
        non_blocking_result = SufficiencyPolicyResult(
            coverage=1.0,
            gap_types=(GapType.UNRESOLVABLE,),
        )
        self.assertTrue(blocking_result.blocking)
        self.assertFalse(non_blocking_result.blocking)

    def test_no_independently_mutable_blocking_field(self) -> None:
        self.assertNotIn("blocking", SufficiencyPolicyResult.__dataclass_fields__)

    def test_no_independently_mutable_ready_for_analysis_field(self) -> None:
        self.assertNotIn(
            "ready_for_analysis",
            SufficiencyPolicyResult.__dataclass_fields__,
        )

    def test_status_single_source_of_truth_invariant_derived(self) -> None:
        cases = (
            (0.0, (GapType.NO_EVIDENCE,), 0, SufficiencyStatus.MISSING),
            (0.0, (GapType.INSUFFICIENT_DEPTH,), 2, SufficiencyStatus.INSUFFICIENT),
            (0.5, (GapType.INSUFFICIENT_DEPTH,), 2, SufficiencyStatus.PARTIAL),
            (1.0, (), 2, SufficiencyStatus.SUFFICIENT),
            (0.5, (), 2, SufficiencyStatus.PARTIAL),
            (0.0, (GapType.UNRESOLVABLE,), 2, SufficiencyStatus.BLOCKED),
        )
        for coverage, gap_types, evidence_count, expected in cases:
            with self.subTest(coverage=coverage, gap_types=gap_types):
                result = SufficiencyPolicyResult(
                    coverage=coverage,
                    gap_types=gap_types,
                    evidence_count=evidence_count,
                )
                self.assertEqual(result.status, expected)
                self.assertEqual(
                    derive_policy_sufficiency_status(
                        coverage=coverage,
                        gap_types=gap_types,
                        evidence_count=evidence_count,
                    ),
                    expected,
                )


class BackwardCompatibilityTests(unittest.TestCase):
    def test_legacy_information_need_payload_without_evidence_expectation_loads(
        self,
    ) -> None:
        need = InformationNeed.from_dict(
            VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
        )
        self.assertIsNotNone(need)

    def test_legacy_information_need_gets_evidence_expectation_none(self) -> None:
        need = InformationNeed.from_dict(
            VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
        )
        self.assertIsNone(need.evidence_expectation)

    def test_legacy_information_need_roundtrip_remains_readable(self) -> None:
        original = InformationNeed.from_dict(
            VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
        )
        restored = InformationNeed.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertNotIn("evidence_expectation", original.to_dict())

    def test_legacy_research_design_without_evidence_expectation_loads(self) -> None:
        design = ResearchDesign.from_dict(
            {"id": "design-legacy", **VALID_RESEARCH_DESIGN_RESPONSE},
        )
        self.assertIsNotNone(design)
        assert design is not None
        self.assertTrue(
            all(
                need.evidence_expectation is None
                for need in design.information_needs
            ),
        )

    def test_legacy_research_design_roundtrip_remains_readable(self) -> None:
        design = ResearchDesign.from_dict(
            {"id": "design-legacy", **VALID_RESEARCH_DESIGN_RESPONSE},
        )
        assert design is not None
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertEqual(restored, design)

    def test_new_information_need_with_evidence_expectation_serializes(self) -> None:
        need = InformationNeed(
            id="in-new",
            research_question_id="rq-1",
            description="Market size for Serbia.",
            evidence_expectation=_quantitative_expectation(),
        )
        payload = need.to_dict()
        self.assertIn("evidence_expectation", payload)

    def test_new_information_need_deserializes(self) -> None:
        need = InformationNeed(
            id="in-new",
            research_question_id="rq-1",
            description="Market size for Serbia.",
            evidence_expectation=_quantitative_expectation(),
        )
        restored = InformationNeed.from_dict(need.to_dict())
        self.assertEqual(
            restored.evidence_expectation,
            need.evidence_expectation,
        )

    def test_new_information_need_roundtrip_preserves_expectation_exactly(self) -> None:
        need = InformationNeed(
            id="in-new",
            research_question_id="rq-1",
            description="Market size for Serbia.",
            evidence_expectation=_quantitative_expectation(),
        )
        restored = InformationNeed.from_dict(need.to_dict())
        self.assertEqual(restored, need)

    def test_new_research_design_with_evidence_expectation_serializes(self) -> None:
        design = ResearchDesign(
            id="design-new",
            research_questions=(),
            information_needs=(
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-1",
                    description="Market size.",
                    evidence_expectation=_quantitative_expectation(),
                ),
            ),
        )
        payload = design.to_dict()
        self.assertIn(
            "evidence_expectation",
            payload["information_needs"][0],
        )

    def test_new_research_design_deserializes(self) -> None:
        design = ResearchDesign(
            id="design-new",
            research_questions=(),
            information_needs=(
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-1",
                    description="Market size.",
                    evidence_expectation=_quantitative_expectation(),
                ),
            ),
        )
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertIsNotNone(restored.information_needs[0].evidence_expectation)

    def test_new_research_design_roundtrip_preserves_expectations(self) -> None:
        design = ResearchDesign(
            id="design-new",
            research_questions=(),
            information_needs=(
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-1",
                    description="Market size.",
                    evidence_expectation=_quantitative_expectation(),
                ),
            ),
        )
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertEqual(restored, design)

    def test_mixed_research_design_containing_legacy_and_new_information_needs_loads(
        self,
    ) -> None:
        design = ResearchDesign(
            id="design-mixed",
            research_questions=(),
            information_needs=(
                InformationNeed.from_dict(
                    VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
                ),
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-awareness",
                    description="Quantitative market size.",
                    evidence_expectation=_quantitative_expectation(),
                ),
            ),
        )
        self.assertIsNone(design.information_needs[0].evidence_expectation)
        self.assertIsNotNone(design.information_needs[1].evidence_expectation)

    def test_mixed_research_design_roundtrip_works(self) -> None:
        design = ResearchDesign(
            id="design-mixed",
            research_questions=(),
            information_needs=(
                InformationNeed.from_dict(
                    VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
                ),
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-awareness",
                    description="Quantitative market size.",
                    evidence_expectation=_quantitative_expectation(),
                ),
            ),
        )
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertEqual(restored, design)

    def test_canonical_required_aspects_remain_stable_in_mixed_roundtrip(self) -> None:
        aspects = (
            "market_size_value",
            "market_size_basis",
            "market_size_geography",
        )
        design = ResearchDesign(
            id="design-mixed",
            research_questions=(),
            information_needs=(
                InformationNeed.from_dict(
                    VALID_RESEARCH_DESIGN_RESPONSE["information_needs"][0],
                ),
                InformationNeed(
                    id="in-new",
                    research_question_id="rq-awareness",
                    description="Quantitative market size.",
                    evidence_expectation=EvidenceExpectation(
                        nature=EvidenceNature.QUANTITATIVE,
                        required_aspects=aspects,
                    ),
                ),
            ),
        )
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        expectation = restored.information_needs[1].evidence_expectation
        assert expectation is not None
        self.assertEqual(expectation.required_aspects, aspects)

    def test_existing_planner_produced_information_needs_continue_to_construct(
        self,
    ) -> None:
        for payload in VALID_RESEARCH_DESIGN_RESPONSE["information_needs"]:
            need = InformationNeed.from_dict(payload)
            self.assertIsNone(need.evidence_expectation)

    def test_existing_fixtures_without_evidence_expectation_remain_valid(self) -> None:
        design = ResearchDesign.from_dict(
            {"id": "design-fixture", **VALID_RESEARCH_DESIGN_RESPONSE},
        )
        assert design is not None
        self.assertEqual(len(design.information_needs), 2)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_planning_contracts_do_not_import_application_or_infrastructure(
        self,
    ) -> None:
        forbidden = ("application.", "infrastructure.", "agency.")
        package_roots = (
            REPO_ROOT / "domain" / "planning",
            REPO_ROOT / "domain" / "research_quality",
        )
        violations: list[str] = []
        for package_root in package_roots:
            for path in sorted(package_root.rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    module = None
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module = alias.name
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        module = node.module
                    if module and any(
                        module == prefix.rstrip(".") or module.startswith(prefix)
                        for prefix in forbidden
                    ):
                        violations.append(f"{path.relative_to(REPO_ROOT)} -> {module}")
        self.assertEqual(violations, [])

    def test_raw_semantic_decision_is_pure_domain_contract(self) -> None:
        module_path = (
            REPO_ROOT / "domain" / "research_quality" / "raw_semantic_decision.py"
        )
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("infrastructure", source)
        self.assertNotIn("application", source)

    def test_aspect_sets_for_policy_helper_not_wired_to_production(self) -> None:
        expectation = _quantitative_expectation()
        decision = RawSemanticDecision(
            supported_aspects=("market_size_value",),
            missing_aspects=("market_size_basis",),
        )
        required, supported, missing = aspect_sets_for_policy(expectation, decision)
        self.assertEqual(required, set(expectation.required_aspects))
        self.assertEqual(supported, {"market_size_value"})
        self.assertEqual(missing, {"market_size_basis"})


class CanonicalAspectIdentifierTests(unittest.TestCase):
    def test_shared_normalization_helper(self) -> None:
        self.assertEqual(
            canonical_aspect_ids([" aspect_a ", "aspect_b", "aspect_a"]),
            ("aspect_a", "aspect_b"),
        )


if __name__ == "__main__":
    unittest.main()
