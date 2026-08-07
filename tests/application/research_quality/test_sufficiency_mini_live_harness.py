"""Offline tests for the P1-06 M3 semantic sufficiency mini-live harness."""

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
HARNESS_SCRIPT = SCRIPTS_DIR / "run_sufficiency_mini_live.py"

for path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import sufficiency_mini_live_harness as harness
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.semantic_decision_normalizer import LEGACY_NEED_ASPECT_ID
from domain.research_quality.sufficiency_status import SufficiencyStatus


class TestMiniLiveFixtures(unittest.TestCase):
    def test_both_scenarios_use_legacy_evidence_expectation(self) -> None:
        for scenario in harness.all_mini_live_scenarios():
            self.assertIsNone(scenario.information_need.evidence_expectation)

    def test_scenario_a_has_multiple_independent_sources(self) -> None:
        scenario = harness.scenario_a_fixtures()
        source_ids = {item.source_id for item in scenario.evidence}
        self.assertGreaterEqual(len(scenario.evidence), 2)
        self.assertGreaterEqual(len(source_ids), 2)

    def test_scenario_b_has_evidence_but_is_insufficient_offline(self) -> None:
        scenario = harness.scenario_b_fixtures()
        result = harness.evaluate_scenario_offline(scenario)
        self.assertGreater(result.evidence_count, 0)
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertNotEqual(result.final_assessment.status, SufficiencyStatus.MISSING)


class TestOfflineHarnessPath(unittest.TestCase):
    def test_offline_harness_runs_both_scenarios(self) -> None:
        results = harness.run_offline_harness()
        self.assertEqual(len(results), 2)
        self.assertEqual(
            {item.scenario_id for item in results},
            {harness.SCENARIO_A_ID, harness.SCENARIO_B_ID},
        )

    def test_offline_fixture_expectations_pass(self) -> None:
        for result in harness.run_offline_harness():
            acceptance = harness.validate_offline_fixture_expectations(result)
            self.assertTrue(acceptance.passed, acceptance.failures)

    def test_scenario_a_offline_policy_and_assessment(self) -> None:
        result = harness.evaluate_scenario_offline(harness.scenario_a_fixtures())
        self.assertEqual(result.policy.coverage, 1.0)
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(result.final_assessment.search_directives, ())

    def test_scenario_b_offline_policy_and_assessment(self) -> None:
        result = harness.evaluate_scenario_offline(harness.scenario_b_fixtures())
        self.assertEqual(result.policy.coverage, 0.0)
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertIn(LEGACY_NEED_ASPECT_ID, result.final_assessment.search_directives)


class TestReportFormatting(unittest.TestCase):
    def test_report_json_is_structured(self) -> None:
        report = harness.format_report(harness.run_offline_harness())
        payload = json.loads(report)
        self.assertEqual(len(payload["scenarios"]), 2)
        first = payload["scenarios"][0]
        self.assertIn("raw_semantic_decision", first)
        self.assertIn("policy", first)
        self.assertIn("final_assessment", first)
        self.assertIn("telemetry", first)
        self.assertIn("attempt_history", first["telemetry"])
        self.assertIn("total_usage", payload)


class TestFakeAssessorPath(unittest.TestCase):
    def test_evaluate_from_raw_semantic_matches_offline_expectations(self) -> None:
        scenario = harness.scenario_a_fixtures()
        raw = RawSemanticDecision(
            supported_aspects=(LEGACY_NEED_ASPECT_ID,),
            missing_aspects=(),
            semantic_conflicts=(),
            confidence=0.95,
            reason="Fake assessor sufficient path.",
        )
        result = harness.evaluate_from_raw_semantic(scenario=scenario, raw_semantic=raw)
        acceptance = harness.validate_offline_fixture_expectations(result)
        self.assertTrue(acceptance.passed, acceptance.failures)


class TestLiveAcceptanceChecks(unittest.TestCase):
    def test_live_validator_flags_unexpected_aspects(self) -> None:
        offline = harness.evaluate_scenario_offline(harness.scenario_a_fixtures())
        bad_raw = RawSemanticDecision(
            supported_aspects=("unexpected_aspect",),
            missing_aspects=(),
            semantic_conflicts=(),
            confidence=0.9,
            reason="bad aspect",
        )
        result = harness.ScenarioRunResult(
            scenario_id=offline.scenario_id,
            information_need_id=offline.information_need_id,
            evidence_count=offline.evidence_count,
            independent_source_count=offline.independent_source_count,
            raw_semantic=bad_raw,
            normalized=offline.normalized,
            policy=offline.policy,
            final_assessment=offline.final_assessment,
            telemetry=offline.telemetry,
            mode="live",
        )
        acceptance = harness.validate_live_acceptance(result)
        self.assertFalse(acceptance.passed)
        self.assertTrue(any("unexpected aspect" in item for item in acceptance.failures))

    def test_live_validator_flags_retries_as_not_clean_first_pass(self) -> None:
        result = harness.evaluate_scenario_offline(harness.scenario_a_fixtures())
        result.mode = "live"
        result.telemetry.llm_calls = 2
        result.telemetry.retries = 1
        result.telemetry.attempts = 2
        acceptance = harness.validate_live_acceptance(result)
        self.assertFalse(acceptance.passed)
        self.assertTrue(
            any("not clean first-pass acceptance" in item for item in acceptance.failures)
        )


class TestFailFastSequencing(unittest.TestCase):
    def test_run_live_harness_stops_before_scenario_b_on_scenario_a_failure(self) -> None:
        scenario_a = harness.scenario_a_fixtures()
        scenario_b = harness.scenario_b_fixtures()
        assessor = MagicMock()

        def fake_live(*, scenario, assessor):  # noqa: ARG001
            if scenario.scenario_id == harness.SCENARIO_A_ID:
                result = harness.evaluate_scenario_offline(scenario)
                result.mode = "live"
                result.raw_semantic = RawSemanticDecision(
                    supported_aspects=(),
                    missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                    semantic_conflicts=(),
                    confidence=0.2,
                    reason="forced insufficient for fail-fast test",
                )
                return harness.evaluate_from_raw_semantic(
                    scenario=scenario,
                    raw_semantic=result.raw_semantic,
                    mode="live",
                    telemetry=harness.ScenarioTelemetry(llm_calls=1, attempts=1),
                )
            raise AssertionError("Scenario B must not be invoked when Scenario A fails")

        with patch.object(harness, "evaluate_scenario_live", side_effect=fake_live):
            results = harness.run_live_harness(assessor)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].scenario_id, scenario_a.scenario_id)
        self.assertEqual(scenario_b.scenario_id, harness.SCENARIO_B_ID)


class TestOptInScriptBehavior(unittest.TestCase):
    def test_script_exits_zero_offline_without_env_flag(self) -> None:
        env = os.environ.copy()
        env.pop(harness.MINI_LIVE_ENV_FLAG, None)
        completed = subprocess.run(
            [sys.executable, str(HARNESS_SCRIPT)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("offline (no provider)", completed.stdout)
        json_start = completed.stdout.index("{")
        json_end = completed.stdout.index("=== Acceptance summary ===")
        payload = json.loads(completed.stdout[json_start:json_end].strip())
        self.assertEqual(payload["total_usage"]["llm_calls"], 0)

    def test_build_production_assessor_uses_config_tokens(self) -> None:
        from application.config import ApplicationConfig

        config = ApplicationConfig.from_env()
        assessor = harness.build_production_semantic_assessor(config)
        self.assertEqual(
            assessor._structured_output._max_output_tokens,
            config.sufficiency_max_output_tokens,
        )
        self.assertEqual(
            assessor._structured_output._reasoning_effort,
            config.sufficiency_reasoning_effort,
        )


class TestEvaluateScenarioLiveNoProvider(unittest.TestCase):
    def test_live_path_env_flag_name(self) -> None:
        self.assertEqual(harness.MINI_LIVE_ENV_FLAG, "SUFFICIENCY_MINI_LIVE")

    @patch("sufficiency_mini_live_harness.raw_semantic_decision_from_payload")
    @patch("sufficiency_mini_live_harness.time.perf_counter", side_effect=[0.0, 0.5])
    def test_evaluate_scenario_live_observable_path_without_real_llm(
        self,
        _perf_counter: MagicMock,
        raw_from_payload: MagicMock,
    ) -> None:
        scenario = harness.scenario_a_fixtures()
        raw_from_payload.return_value = RawSemanticDecision(
            supported_aspects=(LEGACY_NEED_ASPECT_ID,),
            missing_aspects=(),
            semantic_conflicts=(),
            confidence=0.92,
            reason="mocked provider",
        )
        assessor = MagicMock()
        assessor._structured_output.generate.return_value = {"mock": "payload"}
        assessor._structured_output.last_telemetry = {
            "attempts": 1,
            "finish_reason": "stop",
            "output_tokens": 120,
            "max_output_tokens": 8192,
        }
        assessor._structured_output.attempt_history = ()

        result = harness.evaluate_scenario_live(scenario=scenario, assessor=assessor)
        assessor._structured_output.generate.assert_called_once()
        self.assertEqual(result.mode, "live")
        self.assertEqual(result.telemetry.llm_calls, 1)
        self.assertEqual(result.telemetry.attempt_history, ())
        self.assertEqual(result.final_assessment.status, SufficiencyStatus.SUFFICIENT)


if __name__ == "__main__":
    unittest.main()
