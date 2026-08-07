"""P1-06 M3.5 resolvability boundary hardening tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import sufficiency_mini_live_harness as harness
from application.research_quality.raw_semantic_decision_contract import (
    evaluate_raw_semantic_decision_payload,
    raw_semantic_decision_output_instructions,
)
from application.research_quality.semantic_sufficiency_adapter import (
    derive_legacy_search_directives,
    semantic_assessment_from_raw_decision,
)
from domain.planning.research_design import InformationNeed
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    UNRESOLVABLE_CONFLICT_ID,
)
from domain.research_quality.sufficiency_policy import apply_sufficiency_policy
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    _system_prompt,
)


def _signals(*, evidence_count: int = 2) -> DeterministicSufficiencySignals:
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
        description="Commercial microgreens availability in Belgrade.",
    )


class InsufficientEvidenceBoundaryTests(unittest.TestCase):
    def test_absent_support_maps_to_insufficient_not_blocked(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(),
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                semantic_conflicts=(),
                reason="Current evidence does not answer the need.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertNotIn(GapType.UNRESOLVABLE, assessment.gap_types)
        self.assertIn(GapType.INSUFFICIENT_DEPTH, assessment.gap_types)
        self.assertEqual(assessment.coverage, 0.0)

    def test_lack_of_evidence_is_not_semantic_conflict(self) -> None:
        raw = RawSemanticDecision(
            supported_aspects=(),
            missing_aspects=(LEGACY_NEED_ASPECT_ID,),
            semantic_conflicts=(),
            reason="No supporting evidence for the need.",
        )
        self.assertEqual(raw.semantic_conflicts, ())
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(),
            raw_semantic=raw,
        )
        self.assertNotIn(GapType.CONFLICTING_EVIDENCE, assessment.gap_types)

    def test_lack_of_evidence_is_not_unresolvable(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Insufficient current evidence.",
            ),
        )
        self.assertNotIn(GapType.UNRESOLVABLE, assessment.gap_types)
        self.assertNotEqual(assessment.status, SufficiencyStatus.BLOCKED)

    def test_evidence_count_gt_zero_never_missing(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=3),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Nothing supported yet.",
            ),
        )
        self.assertNotEqual(assessment.status, SufficiencyStatus.MISSING)


class ContradictoryEvidenceTests(unittest.TestCase):
    def test_substantive_conflict_maps_to_conflicting_evidence(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(LEGACY_NEED_ASPECT_ID,),
                semantic_conflicts=("demand_increasing_vs_declining",),
                reason="Sources disagree on demand direction.",
            ),
        )
        self.assertIn(GapType.CONFLICTING_EVIDENCE, assessment.gap_types)
        self.assertNotIn(GapType.UNRESOLVABLE, assessment.gap_types)


class MisclassifiedUnresolvableGuardTests(unittest.TestCase):
    def test_scenario_b_shape_maps_to_insufficient_not_blocked(self) -> None:
        """Third mini-live misclassification: unresolvable + explicit missing."""
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=2),
            raw_semantic=RawSemanticDecision(
                supported_aspects=(),
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
                reason="Cannot be resolved with available sources.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertNotIn(GapType.UNRESOLVABLE, assessment.gap_types)
        self.assertIn(GapType.INSUFFICIENT_DEPTH, assessment.gap_types)

    def test_contract_rejects_unresolvable_with_explicit_missing(self) -> None:
        rejection = evaluate_raw_semantic_decision_payload(
            {
                "supported_aspects": [],
                "missing_aspects": [LEGACY_NEED_ASPECT_ID],
                "semantic_conflicts": [UNRESOLVABLE_CONFLICT_ID],
                "confidence": 0.3,
                "reason": "Insufficient evidence mislabeled unresolvable.",
            }
        )
        self.assertEqual(rejection, "misclassified_unresolvable")


class GenuineUnresolvableTests(unittest.TestCase):
    def test_genuine_unresolvable_without_explicit_missing_stays_blocked(self) -> None:
        assessment = apply_sufficiency_policy(
            information_need=_legacy_need(),
            evidence_expectation=None,
            signals=_signals(evidence_count=1),
            raw_semantic=RawSemanticDecision(
                semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
                reason="Evidence proves the need cannot be answered by research.",
            ),
        )
        self.assertEqual(assessment.status, SufficiencyStatus.BLOCKED)
        self.assertIn(GapType.UNRESOLVABLE, assessment.gap_types)


class MiniLiveScenarioRegressionTests(unittest.TestCase):
    def test_scenario_a_remains_sufficient(self) -> None:
        result = harness.evaluate_scenario_offline(harness.scenario_a_fixtures())
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.SUFFICIENT)
        acceptance = harness.validate_offline_fixture_expectations(result)
        self.assertTrue(acceptance.passed, acceptance.failures)

    def test_scenario_b_shape_maps_to_insufficient(self) -> None:
        scenario = harness.scenario_b_fixtures()
        raw = RawSemanticDecision(
            supported_aspects=(),
            missing_aspects=(LEGACY_NEED_ASPECT_ID,),
            semantic_conflicts=(),
            confidence=0.35,
            reason="Evidence does not establish commercial availability.",
        )
        result = harness.evaluate_from_raw_semantic(scenario=scenario, raw_semantic=raw)
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(result.policy.coverage, 0.0)
        self.assertNotIn(GapType.UNRESOLVABLE, result.policy.gap_types)

    def test_scenario_b_targeted_research_remains_actionable(self) -> None:
        scenario = harness.scenario_b_fixtures()
        raw = RawSemanticDecision(
            supported_aspects=(),
            missing_aspects=(LEGACY_NEED_ASPECT_ID,),
            semantic_conflicts=(),
            reason="Need not supported.",
        )
        result = harness.evaluate_from_raw_semantic(scenario=scenario, raw_semantic=raw)
        self.assertIn(
            LEGACY_NEED_ASPECT_ID,
            result.final_assessment.search_directives,
        )
        self.assertEqual(
            derive_legacy_search_directives(
                status=result.final_assessment.status,
                missing_aspects=result.final_assessment.missing_aspects,
            ),
            (LEGACY_NEED_ASPECT_ID,),
        )

    def test_scenario_b_misclassified_live_shape_policy_guard(self) -> None:
        scenario = harness.scenario_b_fixtures()
        raw = RawSemanticDecision(
            supported_aspects=(),
            missing_aspects=(LEGACY_NEED_ASPECT_ID,),
            semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
            reason="Third mini-live misclassification.",
        )
        result = harness.evaluate_from_raw_semantic(scenario=scenario, raw_semantic=raw)
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertIn(
            LEGACY_NEED_ASPECT_ID,
            result.final_assessment.search_directives,
        )


class PromptContractHardeningTests(unittest.TestCase):
    def test_prompt_defines_conflicts_as_evidence_contradictions_only(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("substantive contradictions", instructions)
        self.assertIn("between evidence items only", instructions)

    def test_prompt_forbids_unresolvable_for_insufficient_evidence(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn(
            'Do NOT output "unresolvable" merely because current evidence is insufficient.',
            instructions,
        )

    def test_system_prompt_does_not_conflate_available_sources_with_unresolvable(
        self,
    ) -> None:
        prompt = _system_prompt()
        self.assertNotIn("cannot be answered with available sources", prompt)


class AdapterBlockedVsInsufficientTests(unittest.TestCase):
    def test_insufficient_has_search_directives_blocked_does_not(self) -> None:
        insufficient = semantic_assessment_from_raw_decision(
            information_need=_legacy_need(),
            signals=_signals(),
            raw_semantic=RawSemanticDecision(
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                reason="Insufficient.",
            ),
        )
        blocked = semantic_assessment_from_raw_decision(
            information_need=_legacy_need(),
            signals=_signals(evidence_count=1),
            raw_semantic=RawSemanticDecision(
                semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
                reason="Genuinely unresolvable.",
            ),
        )
        self.assertEqual(insufficient.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(insufficient.search_directives, (LEGACY_NEED_ASPECT_ID,))
        self.assertEqual(blocked.status, SufficiencyStatus.BLOCKED)
        self.assertEqual(blocked.search_directives, ())


if __name__ == "__main__":
    unittest.main()
