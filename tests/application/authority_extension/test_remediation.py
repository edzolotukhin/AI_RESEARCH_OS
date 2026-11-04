from __future__ import annotations

import unittest
from dataclasses import replace

from application.authority_extension.remediation import (
    ExtensionCoverageEvaluator,
    _coverage_progress,
)
from domain.evidence.evidence import Evidence
from domain.planning.research_design import (
    EvidenceCoverageContract,
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
    TemporalGranularity,
)


def _design(*, explicit: bool = True) -> ResearchDesign:
    coverage = (
        EvidenceCoverageContract(
            temporal_granularity=TemporalGranularity.ANNUAL,
            required_periods=("2021", "2022"),
            required_observations=("turnover",),
            required_metric="nominal_turnover",
            required_authority_kinds=("nominal",),
            minimum_independent_sources=2,
            geography="UA",
            eligible_source_types=("official_statistics",),
        )
        if explicit
        else None
    )
    return ResearchDesign(
        "design",
        (ResearchQuestion("rq", "Retail turnover"),),
        (InformationNeed(
            "in1",
            "rq",
            "Nominal turnover",
            timeframe="2021-2022",
            geography="UA",
            evidence_coverage=coverage,
        ),),
    )


def _evidence(identifier: str, source: str, *, periods: str = "2021 2022") -> Evidence:
    return Evidence(
        identifier,
        "project",
        source,
        f"checksum-{source}",
        "extension",
        "design",
        f"nominal_turnover {periods}",
        f"nominal_turnover {periods}",
        "2026-01-01T00:00:00Z",
        research_question_refs=("rq",),
        information_need_refs=("in1",),
        deduplication_key=identifier,
        metadata={
            "observation_period": periods,
            "observation_keys": ["turnover"],
            "source_type": "official_statistics",
            "acquired_content_identity": source,
            "semantic_assignment": {
                "required_aspect_refs": ["nominal_turnover"],
                "geography_applicability": ["UA"],
            },
        },
    )


class ExtensionCoverageEvaluatorTests(unittest.TestCase):
    def test_explicit_contract_requires_temporal_and_source_independence(self) -> None:
        result = ExtensionCoverageEvaluator().evaluate(
            design=_design(),
            evidence=(_evidence("e1", "source-a", periods="2021"),),
        )
        self.assertFalse(result.ready_for_analysis)
        need = result.research_question_assessments[0].information_need_assessments[0]
        self.assertIn("period:2022", need.missing_aspects)
        self.assertIn("independent_sources:1", need.missing_aspects)

    def test_explicit_contract_produces_readiness_proof(self) -> None:
        result = ExtensionCoverageEvaluator().evaluate(
            design=_design(),
            evidence=(
                _evidence("e1", "source-a"),
                _evidence("e2", "source-b"),
            ),
        )
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(result.blocking_information_need_ids, ())

    def test_legacy_contract_preserves_year_and_two_source_policy(self) -> None:
        result = ExtensionCoverageEvaluator().evaluate(
            design=_design(explicit=False),
            evidence=(
                _evidence("e1", "source-a"),
                _evidence("e2", "source-b"),
            ),
        )
        self.assertTrue(result.ready_for_analysis)

    def test_ineligible_source_type_does_not_authorize_analysis(self) -> None:
        first = _evidence("e1", "source-a")
        second = _evidence("e2", "source-b")
        first.metadata["source_type"] = "blog"
        second.metadata["source_type"] = "blog"
        result = ExtensionCoverageEvaluator().evaluate(
            design=_design(),
            evidence=(first, second),
        )
        self.assertFalse(result.ready_for_analysis)

    def test_malformed_observation_format_does_not_authorize_analysis(self) -> None:
        value = _evidence("e1", "source-a")
        second = _evidence("e2", "source-b")
        value.metadata["observation_period"] = "not-a-period"
        value.metadata["observation_keys"] = {"turnover": True}
        second.metadata["observation_period"] = "not-a-period"
        result = ExtensionCoverageEvaluator().evaluate(
            design=_design(), evidence=(value, second),
        )
        self.assertFalse(result.ready_for_analysis)

    def test_foreign_lineage_is_excluded_from_initial_readiness(self) -> None:
        foreign = replace(_evidence("e1", "source-a"), workflow_run_id="foreign")
        local = _evidence("e2", "source-b")
        result = ExtensionCoverageEvaluator(
            project_id="project",
            research_design_id="design",
            allowed_workflow_run_ids=("extension",),
        ).evaluate(design=_design(), evidence=(foreign, local))
        self.assertFalse(result.ready_for_analysis)

    def test_repeated_period_is_not_material_progress(self) -> None:
        evaluator = ExtensionCoverageEvaluator()
        before = evaluator.evaluate(
            design=_design(), evidence=(_evidence("e1", "source-a", periods="2021"),)
        )
        after = evaluator.evaluate(
            design=_design(),
            evidence=(
                _evidence("e1", "source-a", periods="2021"),
                _evidence("e2", "source-a", periods="2021"),
            ),
        )
        self.assertFalse(_coverage_progress(before, after, "in1"))

    def test_missing_period_reduction_is_material_progress(self) -> None:
        evaluator = ExtensionCoverageEvaluator()
        before = evaluator.evaluate(
            design=_design(), evidence=(_evidence("e1", "source-a", periods="2021"),)
        )
        after = evaluator.evaluate(
            design=_design(),
            evidence=(
                _evidence("e1", "source-a", periods="2021"),
                _evidence("e2", "source-b", periods="2022"),
            ),
        )
        self.assertTrue(_coverage_progress(before, after, "in1"))

    def test_other_need_readiness_is_not_progress_for_target_need(self) -> None:
        evaluator = ExtensionCoverageEvaluator()
        before = evaluator.evaluate(
            design=_design(), evidence=(_evidence("e1", "source-a", periods="2021"),)
        )
        after = evaluator.evaluate(
            design=_design(), evidence=(_evidence("e1", "source-a", periods="2021"),)
        )
        self.assertFalse(_coverage_progress(before, after, "other-need"))


if __name__ == "__main__":
    unittest.main()
