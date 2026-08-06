"""Tests for RQCL v1 research sufficiency domain models (P1-01)."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from domain.common.exceptions import ValidationError
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus

REPO_ROOT = Path(__file__).resolve().parents[3]


def _sufficient_need(
    *,
    need_id: str = "in-1",
    rq_id: str = "rq-1",
) -> InformationNeedAssessment:
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=SufficiencyStatus.SUFFICIENT,
        evidence_count=3,
        independent_source_count=2,
        source_quality=0.8,
        confidence=0.9,
        reason="Evidence covers the need.",
    )


def _missing_need(
    *,
    need_id: str = "in-1",
    rq_id: str = "rq-1",
) -> InformationNeedAssessment:
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=SufficiencyStatus.MISSING,
        evidence_count=0,
        gap_types=(GapType.NO_EVIDENCE,),
        reason="No relevant evidence.",
    )


def _partial_need(
    *,
    need_id: str = "in-2",
    rq_id: str = "rq-1",
) -> InformationNeedAssessment:
    return InformationNeedAssessment(
        information_need_id=need_id,
        research_question_id=rq_id,
        status=SufficiencyStatus.PARTIAL,
        evidence_count=2,
        gap_types=(GapType.INSUFFICIENT_DEPTH,),
        missing_aspects=("recent market size",),
        reason="Coverage is incomplete.",
    )


def _ready_rq(
    *,
    rq_id: str = "rq-1",
    needs: tuple[InformationNeedAssessment, ...] | None = None,
) -> ResearchReadinessAssessment:
    assessments = needs or (_sufficient_need(rq_id=rq_id),)
    return ResearchReadinessAssessment(
        research_question_id=rq_id,
        information_need_assessments=assessments,
        ready_for_analysis=True,
        reason="All information needs sufficient.",
    )


class InformationNeedAssessmentTests(unittest.TestCase):
    def test_valid_sufficient_assessment(self) -> None:
        assessment = _sufficient_need()
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(assessment.evidence_count, 3)

    def test_missing_with_evidence_count_forbidden(self) -> None:
        with self.assertRaises(ValidationError):
            InformationNeedAssessment(
                information_need_id="in-1",
                research_question_id="rq-1",
                status=SufficiencyStatus.MISSING,
                evidence_count=1,
            )

    def test_negative_counts_forbidden(self) -> None:
        with self.assertRaises(ValidationError):
            InformationNeedAssessment(
                information_need_id="in-1",
                research_question_id="rq-1",
                status=SufficiencyStatus.SUFFICIENT,
                evidence_count=-1,
            )

    def test_score_range_validation(self) -> None:
        with self.assertRaises(ValidationError):
            InformationNeedAssessment(
                information_need_id="in-1",
                research_question_id="rq-1",
                status=SufficiencyStatus.SUFFICIENT,
                evidence_count=1,
                confidence=1.5,
            )

    def test_sufficient_rejects_blocking_gap_types(self) -> None:
        with self.assertRaises(ValidationError):
            InformationNeedAssessment(
                information_need_id="in-1",
                research_question_id="rq-1",
                status=SufficiencyStatus.SUFFICIENT,
                evidence_count=2,
                gap_types=(GapType.NO_EVIDENCE,),
            )

    def test_deterministic_to_dict_from_dict_roundtrip(self) -> None:
        original = InformationNeedAssessment(
            information_need_id="in-1",
            research_question_id="rq-1",
            status=SufficiencyStatus.PARTIAL,
            evidence_count=2,
            independent_source_count=1,
            source_quality=0.7,
            freshness=0.6,
            source_diversity=0.5,
            quantitative_evidence_present=False,
            contradictions=("claim A vs claim B",),
            missing_aspects=("pricing detail",),
            gap_types=(GapType.INSUFFICIENT_DEPTH, GapType.UNRESOLVABLE),
            search_directives=("find recent pricing reports",),
            confidence=0.65,
            reason="Needs more depth.",
        )
        payload = original.to_dict()
        restored = InformationNeedAssessment.from_dict(payload)
        self.assertEqual(restored, original)
        self.assertEqual(
            json.dumps(original.to_dict(), sort_keys=True),
            json.dumps(restored.to_dict(), sort_keys=True),
        )


class ResearchReadinessAssessmentTests(unittest.TestCase):
    def test_rejects_foreign_information_need(self) -> None:
        foreign = _sufficient_need(need_id="in-1", rq_id="rq-other")
        with self.assertRaises(ValidationError):
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(foreign,),
                ready_for_analysis=False,
                blocking_information_need_ids=("in-1",),
            )

    def test_partial_blocks_readiness(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(_partial_need(),),
                ready_for_analysis=True,
            )

    def test_missing_blocks_readiness(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchReadinessAssessment(
                research_question_id="rq-1",
                information_need_assessments=(_missing_need(),),
                ready_for_analysis=True,
            )

    def test_ready_true_only_when_all_needs_sufficient(self) -> None:
        assessment = ResearchReadinessAssessment(
            research_question_id="rq-1",
            information_need_assessments=(
                _sufficient_need(need_id="in-1"),
                _sufficient_need(need_id="in-2"),
            ),
            ready_for_analysis=True,
        )
        self.assertTrue(assessment.ready_for_analysis)
        self.assertEqual(assessment.blocking_information_need_ids, ())

    def test_ready_false_requires_blocking_ids(self) -> None:
        assessment = ResearchReadinessAssessment(
            research_question_id="rq-1",
            information_need_assessments=(
                _sufficient_need(need_id="in-1"),
                _partial_need(need_id="in-2"),
            ),
            ready_for_analysis=False,
            blocking_information_need_ids=("in-2",),
        )
        self.assertFalse(assessment.ready_for_analysis)
        self.assertEqual(assessment.blocking_information_need_ids, ("in-2",))


class ResearchReadinessResultTests(unittest.TestCase):
    def test_run_level_readiness_aggregation_ready(self) -> None:
        result = ResearchReadinessResult(
            research_question_assessments=(
                _ready_rq(rq_id="rq-1"),
                _ready_rq(rq_id="rq-2"),
            ),
            ready_for_analysis=True,
        )
        self.assertTrue(result.ready_for_analysis)
        self.assertFalse(result.targeted_research_required)
        self.assertEqual(result.blocking_research_question_ids, ())
        self.assertEqual(result.blocking_information_need_ids, ())

    def test_run_level_readiness_aggregation_not_ready(self) -> None:
        blocked_rq = ResearchReadinessAssessment(
            research_question_id="rq-2",
            information_need_assessments=(_missing_need(need_id="in-3", rq_id="rq-2"),),
            ready_for_analysis=False,
            blocking_information_need_ids=("in-3",),
        )
        result = ResearchReadinessResult(
            research_question_assessments=(
                _ready_rq(rq_id="rq-1"),
                blocked_rq,
            ),
            ready_for_analysis=False,
            blocking_research_question_ids=("rq-2",),
            blocking_information_need_ids=("in-3",),
            targeted_research_required=True,
        )
        self.assertFalse(result.ready_for_analysis)
        self.assertTrue(result.targeted_research_required)

    def test_targeted_research_required_semantics(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchReadinessResult(
                research_question_assessments=(_ready_rq(),),
                ready_for_analysis=True,
                targeted_research_required=True,
            )
        with self.assertRaises(ValidationError):
            ResearchReadinessResult(
                research_question_assessments=(
                    ResearchReadinessAssessment(
                        research_question_id="rq-1",
                        information_need_assessments=(_missing_need(),),
                        ready_for_analysis=False,
                        blocking_information_need_ids=("in-1",),
                    ),
                ),
                ready_for_analysis=False,
                blocking_research_question_ids=("rq-1",),
                blocking_information_need_ids=("in-1",),
                targeted_research_required=False,
            )
        blocked_only = ResearchReadinessResult(
            research_question_assessments=(
                ResearchReadinessAssessment(
                    research_question_id="rq-1",
                    information_need_assessments=(
                        InformationNeedAssessment(
                            information_need_id="in-1",
                            research_question_id="rq-1",
                            status=SufficiencyStatus.BLOCKED,
                            evidence_count=2,
                            gap_types=(GapType.UNRESOLVABLE,),
                            reason="Need cannot be resolved with available sources.",
                        ),
                    ),
                    ready_for_analysis=False,
                    blocking_information_need_ids=("in-1",),
                ),
            ),
            ready_for_analysis=False,
            blocking_research_question_ids=("rq-1",),
            blocking_information_need_ids=("in-1",),
            targeted_research_required=False,
        )
        self.assertFalse(blocked_only.targeted_research_required)

    def test_run_level_roundtrip(self) -> None:
        original = ResearchReadinessResult(
            research_question_assessments=(
                _ready_rq(rq_id="rq-1"),
                ResearchReadinessAssessment(
                    research_question_id="rq-2",
                    information_need_assessments=(_partial_need(need_id="in-3", rq_id="rq-2"),),
                    ready_for_analysis=False,
                    blocking_information_need_ids=("in-3",),
                ),
            ),
            ready_for_analysis=False,
            blocking_research_question_ids=("rq-2",),
            blocking_information_need_ids=("in-3",),
            targeted_research_required=True,
            termination_reason="",
        )
        restored = ResearchReadinessResult.from_dict(original.to_dict())
        self.assertEqual(restored, original)


class ResearchQualityArchitectureTests(unittest.TestCase):
    def test_domain_package_does_not_import_application_or_infrastructure(self) -> None:
        forbidden = ("application.", "infrastructure.", "agency.")
        violations: list[str] = []
        package_root = REPO_ROOT / "domain" / "research_quality"
        for path in sorted(package_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                        if any(
                            module == prefix.rstrip(".")
                            or module.startswith(prefix)
                            for prefix in forbidden
                        ):
                            violations.append(f"{path.name} -> {module}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                    if any(
                        module == prefix.rstrip(".")
                        or module.startswith(prefix)
                        for prefix in forbidden
                    ):
                        violations.append(f"{path.name} -> {module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
