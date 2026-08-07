"""P1-06 M3.1 boundary fix tests: search_directives ownership and legacy aspect."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from application.research_quality.semantic_sufficiency_adapter import (
    derive_legacy_search_directives,
    semantic_assessment_from_raw_decision,
)
from domain.common.exceptions import ValidationError
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    derive_semantic_coverage,
    legacy_required_aspects,
    normalize_semantic_decision,
)
from domain.research_quality.sufficiency_policy import apply_sufficiency_policy
from domain.research_quality.sufficiency_status import SufficiencyStatus

REPO_ROOT = Path(__file__).resolve().parents[3]


def _signals(*, evidence_count: int = 1) -> DeterministicSufficiencySignals:
    return DeterministicSufficiencySignals(
        information_need_id="in-1",
        research_question_id="rq-1",
        evidence_count=evidence_count,
        independent_source_count=evidence_count,
        evidence_ids=tuple(f"evidence-{index}" for index in range(evidence_count)),
        source_ids=tuple(f"source-{index}" for index in range(evidence_count)),
    )


def _legacy_need() -> InformationNeed:
    return InformationNeed(
        id="in-1",
        research_question_id="rq-1",
        description="Quantitative market size for Serbia.",
    )


class SearchDirectivesOwnershipTests(unittest.TestCase):
    def test_domain_policy_module_has_no_search_directives_behavior(self) -> None:
        source = (
            REPO_ROOT / "domain" / "research_quality" / "sufficiency_policy.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("search_directives", source)

    def test_adapter_maps_missing_aspects_to_legacy_directives(self) -> None:
        assessment = semantic_assessment_from_raw_decision(
            information_need=_legacy_need(),
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Legacy need not supported.",
            ),
        )
        self.assertEqual(assessment.search_directives, (LEGACY_NEED_ASPECT_ID,))

    def test_sufficient_and_blocked_have_empty_directives(self) -> None:
        sufficient = semantic_assessment_from_raw_decision(
            information_need=_legacy_need(),
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Supported.",
            ),
        )
        blocked = semantic_assessment_from_raw_decision(
            information_need=_legacy_need(),
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                semantic_conflicts=("unresolvable",),
                reason="Blocked.",
            ),
        )
        self.assertEqual(sufficient.search_directives, ())
        self.assertEqual(blocked.search_directives, ())

    def test_partial_insufficient_directives_unchanged(self) -> None:
        directives = derive_legacy_search_directives(
            status=SufficiencyStatus.PARTIAL,
            missing_aspects=("aspect_b", "aspect_a"),
        )
        self.assertEqual(directives, ("aspect_a", "aspect_b"))


class LegacyAspectRepeatabilityTests(unittest.TestCase):
    def test_legacy_required_aspects_is_single_synthetic_target(self) -> None:
        self.assertEqual(legacy_required_aspects(), (LEGACY_NEED_ASPECT_ID,))

    def test_legacy_normalization_rejects_invented_aspect_ids(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_semantic_decision(
                raw=RawSemanticDecision(
                    supported_aspects=("market_context",),
                ),
                evidence_expectation=None,
            )

    def test_legacy_supported_yields_coverage_one(self) -> None:
        normalized = normalize_semantic_decision(
            raw=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
            ),
            evidence_expectation=None,
        )
        coverage = derive_semantic_coverage(
            required_aspects=normalized.required_aspects,
            supported_aspects=normalized.supported_aspects,
            missing_aspects=normalized.missing_aspects,
        )
        self.assertEqual(coverage, 1.0)

    def test_legacy_missing_yields_coverage_zero(self) -> None:
        normalized = normalize_semantic_decision(
            raw=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
            ),
            evidence_expectation=None,
        )
        coverage = derive_semantic_coverage(
            required_aspects=normalized.required_aspects,
            supported_aspects=normalized.supported_aspects,
            missing_aspects=normalized.missing_aspects,
        )
        self.assertEqual(coverage, 0.0)

    def test_legacy_unclassified_target_defaults_to_missing(self) -> None:
        normalized = normalize_semantic_decision(
            raw=RawSemanticDecision(reason="No explicit classification."),
            evidence_expectation=None,
        )
        self.assertEqual(normalized.missing_aspects, (LEGACY_NEED_ASPECT_ID,))
        self.assertEqual(normalized.supported_aspects, ())

    def test_legacy_evidence_present_missing_is_not_missing_status(self) -> None:
        decision = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Not supported.",
            ),
        )
        self.assertNotEqual(decision.status, SufficiencyStatus.MISSING)

    def test_legacy_taxonomy_is_stable_across_identical_inputs(self) -> None:
        raw = RawSemanticDecision(
            supported_aspects=(LEGACY_NEED_ASPECT_ID,),
            reason="Supported.",
        )
        first = normalize_semantic_decision(raw=raw, evidence_expectation=None)
        second = normalize_semantic_decision(raw=raw, evidence_expectation=None)
        self.assertEqual(first, second)


class ExpectationBackedBehaviorTests(unittest.TestCase):
    def test_expectation_backed_behavior_unchanged(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUANTITATIVE,
            required_aspects=("market_size_value", "market_size_basis"),
            requires_quantitative_evidence=True,
            minimum_independent_sources=2,
        )
        decision = apply_sufficiency_policy(
            information_need=InformationNeed(
                id="in-1",
                research_question_id="rq-1",
                description="Need",
                evidence_expectation=expectation,
            ),
            evidence_expectation=None,
            signals=DeterministicSufficiencySignals(
                information_need_id="in-1",
                research_question_id="rq-1",
                evidence_count=2,
                independent_source_count=2,
                evidence_ids=("evidence-1", "evidence-2"),
                source_ids=("source-1", "source-2"),
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Complete.",
            ),
        )
        self.assertEqual(decision.status, SufficiencyStatus.SUFFICIENT)

    def test_expectation_backed_unknown_aspect_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_semantic_decision(
                raw=RawSemanticDecision(
                    supported_aspects=("unexpected_aspect",),
                ),
                evidence_expectation=EvidenceExpectation(
                    nature=EvidenceNature.QUALITATIVE,
                    required_aspects=("known_aspect",),
                ),
            )


class RawSemanticDecisionBoundaryTests(unittest.TestCase):
    def test_raw_semantic_decision_has_no_search_fields(self) -> None:
        self.assertNotIn(
            "search_directives",
            RawSemanticDecision.__dataclass_fields__,
        )


class AdapterArchitectureTests(unittest.TestCase):
    def test_adapter_owns_search_directives_mapping(self) -> None:
        source = (
            REPO_ROOT
            / "application"
            / "research_quality"
            / "semantic_sufficiency_adapter.py"
        ).read_text(encoding="utf-8")
        self.assertIn("derive_legacy_search_directives", source)
        tree = ast.parse(source, filename=str(source))
        imports_domain_policy = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "domain.research_quality.sufficiency_policy"
            for node in ast.walk(tree)
        )
        self.assertTrue(imports_domain_policy)


if __name__ == "__main__":
    unittest.main()
