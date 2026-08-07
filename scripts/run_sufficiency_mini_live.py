#!/usr/bin/env python3
"""P1-06 M3 mini-live semantic sufficiency acceptance harness.

Exercises only:
  InformationNeed + fixed Evidence[]
  -> LlmSemanticSufficiencyAssessor (live) or offline fixture path
  -> RawSemanticDecision -> normalizer -> policy -> SemanticSufficiencyAssessment

Does NOT invoke Search, Evidence extraction, Analysis, Report, Review, or WorkflowEngine.

Live provider calls require explicit opt-in:
  SUFFICIENCY_MINI_LIVE=1

Without that flag the harness runs offline fixture validation only (no provider).
"""

from __future__ import annotations

import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_scripts_dir)
for path in (_repo_root, _scripts_dir):
    if path not in sys.path:
        sys.path.insert(0, path)

from application.config import ApplicationConfig
from sufficiency_mini_live_harness import (
    MAX_STRUCTURED_OUTPUT_ATTEMPTS,
    MINI_LIVE_ENV_FLAG,
    aggregate_usage,
    all_mini_live_scenarios,
    build_production_semantic_assessor,
    format_report,
    run_live_harness,
    run_offline_harness,
    validate_live_acceptance,
    validate_offline_fixture_expectations,
)


def _env_flag_enabled() -> bool:
    return os.environ.get(MINI_LIVE_ENV_FLAG, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _print_config(config: ApplicationConfig) -> None:
    print("=== Semantic generation configuration ===")
    print(f"llm_model: {config.llm_model}")
    print(f"sufficiency_reasoning_effort: {config.sufficiency_reasoning_effort}")
    print(f"sufficiency_max_output_tokens: {config.sufficiency_max_output_tokens}")
    print(f"structured_output_max_attempts: {MAX_STRUCTURED_OUTPUT_ATTEMPTS}")
    if config.sufficiency_max_output_tokens != 8192:
        print("WARNING: sufficiency_max_output_tokens is not 8192")
    if config.sufficiency_reasoning_effort != "minimal":
        print("WARNING: sufficiency_reasoning_effort is not minimal")
    print()


def main() -> int:
    live_requested = _env_flag_enabled()

    print("=== P1-06 M3 Semantic Sufficiency Mini-Live Harness ===")
    print(f"{MINI_LIVE_ENV_FLAG}={os.environ.get(MINI_LIVE_ENV_FLAG, '')!r}")
    print(f"mode: {'live' if live_requested else 'offline (no provider)'}")
    print(f"scenarios: {len(all_mini_live_scenarios())}")
    print()

    if live_requested:
        config = ApplicationConfig.from_env()
        _print_config(config)
        assessor = build_production_semantic_assessor(config)
        results = run_live_harness(assessor)
        acceptances = [validate_live_acceptance(item) for item in results]
        if len(results) < len(all_mini_live_scenarios()):
            skipped = [
                scenario.scenario_id
                for scenario in all_mini_live_scenarios()[len(results) :]
            ]
            print("=== Fail-fast stop ===")
            print(
                "Scenario(s) skipped after failure (no provider call): "
                + ", ".join(skipped)
            )
            print()
    else:
        print("Offline mode: using fixture RawSemanticDecision (no provider call).")
        print()
        results = run_offline_harness()
        acceptances = [validate_offline_fixture_expectations(item) for item in results]

    print(format_report(results))
    print()

    print("=== Acceptance summary ===")
    for acceptance in acceptances:
        status = "PASS" if acceptance.passed else "FAIL"
        print(f"{acceptance.scenario_id}: {status}")
        for failure in acceptance.failures:
            print(f"  - {failure}")

    usage = aggregate_usage(results)
    print()
    print("=== Total usage ===")
    for key, value in usage.items():
        print(f"{key}: {value}")

    if any(not item.passed for item in acceptances):
        print()
        print("STOP: at least one scenario failed; no automatic rerun.")
        return 1

    if live_requested:
        print()
        print("Mini-live completed: 2/2 scenarios accepted.")
    else:
        print()
        print("Offline harness validation completed successfully.")
        print("Set SUFFICIENCY_MINI_LIVE=1 to execute real provider calls (after review).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
