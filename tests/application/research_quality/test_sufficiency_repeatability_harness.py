"""Offline tests for the P1-06 semantic sufficiency repeatability gate harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
REPEATABILITY_SCRIPT = SCRIPTS_DIR / "run_sufficiency_repeatability.py"

for path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import sufficiency_mini_live_harness as harness
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import (
    LEGACY_NEED_ASPECT_ID,
    UNRESOLVABLE_CONFLICT_ID,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus


class TestRepeatabilityMatrix(unittest.TestCase):
    def test_matrix_has_exactly_six_executions(self) -> None:
        matrix = harness.repeatability_execution_matrix()
        self.assertEqual(len(matrix), harness.REPEATABILITY_PLANNED_EXECUTIONS)

    def test_execution_order_is_interleaved(self) -> None:
        execution_ids = tuple(item.execution_id for item in harness.repeatability_execution_matrix())
        self.assertEqual(
            execution_ids,
            harness.REPEATABILITY_EXECUTION_ORDER,
        )
        self.assertEqual(execution_ids, ("A1", "B1", "A2", "B2", "A3", "B3"))

    def test_fixtures_are_unchanged_accepted_scenarios(self) -> None:
        matrix = harness.repeatability_execution_matrix()
        scenario_ids = {item.scenario.scenario_id for item in matrix}
        self.assertEqual(
            scenario_ids,
            {harness.SCENARIO_A_ID, harness.SCENARIO_B_ID},
        )
        for item in matrix:
            self.assertIsNone(item.scenario.information_need.evidence_expectation)


class TestRepeatabilityOfflineHarness(unittest.TestCase):
    def test_offline_repeatability_runs_all_six(self) -> None:
        executions = harness.run_repeatability_offline_harness()
        self.assertEqual(len(executions), 6)
        self.assertTrue(all(item.acceptance.passed for item in executions))

    def test_offline_repeatability_verdict_passes(self) -> None:
        executions = harness.run_repeatability_offline_harness()
        verdict, passed = harness.repeatability_verdict(executions)
        self.assertTrue(passed)
        self.assertEqual(
            verdict,
            "P1-06 SEMANTIC SUFFICIENCY REPEATABILITY — PASS",
        )

    def test_artifact_aggregation(self) -> None:
        executions = harness.run_repeatability_offline_harness()
        artifact = harness.build_repeatability_artifact(
            configuration={"llm_model": None},
            executions=executions,
            mode="offline",
            execution_order=harness.REPEATABILITY_EXECUTION_ORDER,
        )
        self.assertEqual(artifact["planned_executions"], 6)
        self.assertEqual(artifact["completed_executions"], 6)
        self.assertTrue(artifact["passed"])
        self.assertEqual(len(artifact["executions"]), 6)
        self.assertIn("aggregate_metrics", artifact)


class TestRepeatabilityFailFast(unittest.TestCase):
    def test_live_repeatability_stops_after_first_failure(self) -> None:
        assessor = MagicMock()
        call_count = {"value": 0}

        def fake_live(*, scenario, assessor):  # noqa: ARG001
            call_count["value"] += 1
            result = harness.evaluate_scenario_offline(scenario)
            result.mode = "live"
            if scenario.scenario_id == harness.SCENARIO_A_ID and call_count["value"] == 1:
                result.raw_semantic = RawSemanticDecision(
                    supported_aspects=(),
                    missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                    semantic_conflicts=(),
                    confidence=0.2,
                    reason="forced A1 failure",
                )
                result = harness.evaluate_from_raw_semantic(
                    scenario=scenario,
                    raw_semantic=result.raw_semantic,
                    mode="live",
                    telemetry=harness.ScenarioTelemetry(
                        attempts=1,
                        llm_calls=1,
                        retries=0,
                    ),
                )
            return result

        with patch.object(harness, "evaluate_scenario_live", side_effect=fake_live):
            executions = harness.run_repeatability_live_harness(assessor)

        self.assertEqual(len(executions), 1)
        self.assertFalse(executions[0].acceptance.passed)
        self.assertEqual(executions[0].execution_id, "A1")

    def test_live_repeatability_stops_on_retry(self) -> None:
        assessor = MagicMock()

        def fake_live(*, scenario, assessor):  # noqa: ARG001
            result = harness.evaluate_scenario_offline(scenario)
            result.mode = "live"
            return harness.evaluate_from_raw_semantic(
                scenario=scenario,
                raw_semantic=result.raw_semantic,
                mode="live",
                telemetry=harness.ScenarioTelemetry(
                    attempts=2,
                    llm_calls=2,
                    retries=1,
                ),
            )

        with patch.object(harness, "evaluate_scenario_live", side_effect=fake_live):
            executions = harness.run_repeatability_live_harness(assessor)

        self.assertEqual(len(executions), 1)
        self.assertFalse(executions[0].acceptance.passed)
        self.assertIsNotNone(executions[0].failure_classification)


class TestRepeatabilityOptIn(unittest.TestCase):
    def test_script_offline_without_live_flag_makes_no_provider_calls(self) -> None:
        env = os.environ.copy()
        env.pop(harness.REPEATABILITY_LIVE_ENV_FLAG, None)
        env.pop(harness.MINI_LIVE_ENV_FLAG, None)
        completed = subprocess.run(
            [sys.executable, str(REPEATABILITY_SCRIPT)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("offline (no provider)", completed.stdout)
        self.assertIn("planned_executions: 6", completed.stdout)
        self.assertIn("A1 B1 A2 B2 A3 B3", completed.stdout)

    def test_repeatability_live_flag_name(self) -> None:
        self.assertEqual(
            harness.REPEATABILITY_LIVE_ENV_FLAG,
            "SUFFICIENCY_REPEATABILITY_LIVE",
        )


class TestRepeatabilityClassification(unittest.TestCase):
    def test_blocked_scenario_b_classified_as_resolvability_regression(self) -> None:
        scenario = harness.scenario_b_fixtures()
        raw = RawSemanticDecision(
            semantic_conflicts=(UNRESOLVABLE_CONFLICT_ID,),
            reason="genuinely unresolvable without explicit missing aspects",
        )
        result = harness.evaluate_from_raw_semantic(
            scenario=scenario,
            raw_semantic=raw,
            mode="live",
            telemetry=harness.ScenarioTelemetry(attempts=1, llm_calls=1),
        )
        acceptance = harness.validate_repeatability_acceptance(result)
        classification = harness.classify_repeatability_failure(
            result=result,
            acceptance=acceptance,
        )
        self.assertEqual(classification, "RESOLVABILITY_REGRESSION")


if __name__ == "__main__":
    unittest.main()
