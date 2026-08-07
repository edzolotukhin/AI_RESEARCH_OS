"""P1-06 M3 deterministic sufficiency policy and semantic boundary tests."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from domain.common.exceptions import ValidationError
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import BLOCKING_GAP_TYPES, GapType
from domain.research_quality.policy_sufficiency_status import (
    derive_policy_sufficiency_status,
)
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    UNRESOLVABLE_CONFLICT_ID,
    normalize_semantic_decision,
)
from domain.research_quality.sufficiency_policy import apply_sufficiency_policy
from domain.research_quality.sufficiency_status import SufficiencyStatus

from application.research_quality.semantic_sufficiency_adapter import (
    semantic_assessment_from_raw_decision,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _signals(
    *,
    evidence_count: int = 1,
    independent_source_count: int | None = None,
    quantitative_evidence_present: bool | None = None,
    deterministic_gap_types: tuple[GapType, ...] = (),
) -> DeterministicSufficiencySignals:
    independent = (
        independent_source_count
        if independent_source_count is not None
        else evidence_count
    )
    return DeterministicSufficiencySignals(
        information_need_id="in-1",
        research_question_id="rq-1",
        evidence_count=evidence_count,
        independent_source_count=independent,
        evidence_ids=tuple(f"evidence-{index}" for index in range(evidence_count)),
        source_ids=tuple(f"source-{index}" for index in range(independent)),
        quantitative_evidence_present=quantitative_evidence_present,
        deterministic_gap_types=deterministic_gap_types,
    )


def _need(*, evidence_expectation: EvidenceExpectation | None = None) -> InformationNeed:
    return InformationNeed(
        id="in-1",
        research_question_id="rq-1",
        description="Quantitative market size for Serbia.",
        evidence_expectation=evidence_expectation,
    )


def _expectation(**overrides: object) -> EvidenceExpectation:
    base = {
        "nature": EvidenceNature.QUANTITATIVE,
        "required_aspects": (
            "market_size_value",
            "market_size_basis",
        ),
        "requires_quantitative_evidence": True,
        "minimum_independent_sources": 2,
    }
    base.update(overrides)
    return EvidenceExpectation(**base)  # type: ignore[arg-type]


class PolicyMatrixTests(unittest.TestCase):
    def test_zero_evidence_is_missing(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=0),
            raw_semantic=RawSemanticDecision(reason="No evidence."),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.MISSING)

    def test_evidence_exists_but_supports_nothing_is_not_missing(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(),
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Evidence does not substantively answer the need.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.MISSING)
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)

    def test_partial_support(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(
                evidence_expectation=_expectation(required_aspects=("a", "b")),
            ),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("a",),
                missing_aspects=("b",),
                reason="Partial support.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.PARTIAL)
        self.assertIn(GapType.INSUFFICIENT_DEPTH, assessment.gap_types)

    def test_complete_support(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(
                evidence_expectation=_expectation(required_aspects=("a", "b")),
            ),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=2,
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("a", "b"),
                reason="Complete support.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(assessment.missing_aspects, ())

    def test_unresolved_semantic_conflict_blocks_sufficient(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
                semantic_conflicts=("market_size_value",),
                reason="Conflicting figures.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertIn(GapType.CONFLICTING_EVIDENCE, assessment.gap_types)

    def test_unresolvable_conflict(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=1),
            raw_semantic=RawSemanticDecision(
                semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
                reason="Need cannot be resolved.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.BLOCKED)
        self.assertIn(GapType.UNRESOLVABLE, assessment.gap_types)

    def test_quantitative_required_but_absent(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(evidence_expectation=_expectation()),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=2,
                quantitative_evidence_present=False,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Qualitative only.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertIn(GapType.MISSING_QUANTITATIVE_DATA, assessment.gap_types)

    def test_quantitative_required_and_present(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(evidence_expectation=_expectation()),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=2,
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Quantitative support present.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)

    def test_minimum_sources_unmet(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(evidence_expectation=_expectation()),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=1,
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Only one independent source.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertIn(GapType.INSUFFICIENT_DIVERSITY, assessment.gap_types)

    def test_minimum_sources_met(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(evidence_expectation=_expectation(minimum_independent_sources=2)),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=2,
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Two independent sources.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)

    def test_legacy_without_evidence_expectation(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=1),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Legacy semantic support.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)

    def test_required_aspects_empty_with_legacy(self) -> None:
        with self.assertRaises(ValidationError):
            apply_sufficiency_policy(
                information_need=_need(),
                evidence_expectation=None,
                signals=_signals(evidence_count=1),
                raw_semantic=RawSemanticDecision(
                    supported_aspects=("derived_aspect",),
                    reason="Invalid legacy aspect.",
                ),
            )

    def test_malformed_semantic_overlap_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_semantic_decision(
                raw=RawSemanticDecision(
                    supported_aspects=("market_size_value",),
                    missing_aspects=("market_size_value",),
                ),
                evidence_expectation=_expectation(),
            )

    def test_complete_coverage_but_formal_requirement_unmet(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(evidence_expectation=_expectation()),
            evidence_expectation=None,
            signals=_signals(
                evidence_count=2,
                independent_source_count=1,
                quantitative_evidence_present=True,
            ),
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_size_value", "market_size_basis"),
                reason="Aspects covered but source diversity unmet.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.SUFFICIENT)

    def test_evidence_count_gt_zero_cannot_yield_missing(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=3),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Nothing supported.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.MISSING)


class StatusDerivationRegressionTests(unittest.TestCase):
    def test_every_status_reachable_from_policy(self) -> None:
        cases = (
            apply_sufficiency_policy(
                information_need=_need(),
                evidence_expectation=None,
                signals=_signals(evidence_count=0),
                raw_semantic=RawSemanticDecision(reason="none"),
            ),
            apply_sufficiency_policy(
                information_need=_need(),
                evidence_expectation=None,
                signals=_signals(evidence_count=2),
                raw_semantic=RawSemanticDecision(
                    missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                    reason="none supported",
                ),
            ),
            apply_sufficiency_policy(
                information_need=_need(
                    evidence_expectation=_expectation(required_aspects=("a", "b")),
                ),
                evidence_expectation=None,
                signals=_signals(evidence_count=2, quantitative_evidence_present=True, independent_source_count=2),
                raw_semantic=RawSemanticDecision(
                    supported_aspects=("a",),
                    missing_aspects=("b",),
                    reason="partial",
                ),
            ),
            apply_sufficiency_policy(
                information_need=_need(
                    evidence_expectation=_expectation(required_aspects=("a",)),
                ),
                evidence_expectation=None,
                signals=_signals(evidence_count=2, quantitative_evidence_present=True, independent_source_count=2),
                raw_semantic=RawSemanticDecision(
                    supported_aspects=("a",),
                    reason="complete",
                ),
            ),
            apply_sufficiency_policy(
                information_need=_need(),
                evidence_expectation=None,
                signals=_signals(evidence_count=1),
                raw_semantic=RawSemanticDecision(
                    semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
                    reason="blocked",
                ),
            ),
        )
        statuses = {item.status for item in cases}
        self.assertEqual(
            statuses,
            {
                SufficiencyStatus.MISSING,
                SufficiencyStatus.INSUFFICIENT,
                SufficiencyStatus.PARTIAL,
                SufficiencyStatus.SUFFICIENT,
                SufficiencyStatus.BLOCKED,
            },
        )


class BlockedVsBlockingAuditTests(unittest.TestCase):
    def test_unresolvable_is_blocked_status_not_blocking_gap_property(self) -> None:
        status = derive_policy_sufficiency_status(
            coverage=0.5,
            gap_types=(GapType.UNRESOLVABLE,),
            evidence_count=2,
        )
        blocking = any(gap in BLOCKING_GAP_TYPES for gap in (GapType.UNRESOLVABLE,))
        self.assertEqual(status, SufficiencyStatus.BLOCKED)
        self.assertFalse(blocking)


class PolicyArchitectureTests(unittest.TestCase):
    def test_policy_module_has_no_provider_or_infrastructure_imports(self) -> None:
        forbidden = ("application.", "infrastructure.", "agency.")
        package_root = REPO_ROOT / "domain" / "research_quality"
        targets = (
            package_root / "sufficiency_policy.py",
            package_root / "semantic_decision_normalizer.py",
            package_root / "policy_sufficiency_status.py",
        )
        violations: list[str] = []
        for path in targets:
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
                    violations.append(f"{path.name} -> {module}")
        self.assertEqual(violations, [])


class SemanticAssessmentAdapterTests(unittest.TestCase):
    def test_adapter_populates_compatible_semantic_assessment(self) -> None:
        assessment = semantic_assessment_from_raw_decision(
            information_need=_need(),
            signals=_signals(evidence_count=1),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
                confidence=0.88,
                reason="Supported.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(assessment.search_directives, ())


if __name__ == "__main__":
    unittest.main()
