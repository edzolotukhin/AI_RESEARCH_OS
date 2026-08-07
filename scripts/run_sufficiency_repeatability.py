#!/usr/bin/env python3
"""P1-06 Semantic Sufficiency repeatability acceptance harness.

Matrix: Scenario A × 3 + Scenario B × 3 (A1 B1 A2 B2 A3 B3).

Exercises only the production Semantic Sufficiency boundary:
  fixed InformationNeed + fixed Evidence[]
  -> LlmSemanticSufficiencyAssessor (live) or offline fixture path
  -> RawSemanticDecision -> normalizer -> policy -> SemanticSufficiencyAssessment

Does NOT invoke Search, Evidence extraction, Analysis, Report, Review, or WorkflowEngine.

Live provider calls require explicit opt-in:
  SUFFICIENCY_REPEATABILITY_LIVE=1

Without that flag the harness runs offline matrix validation only (no provider).
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
    DEFAULT_REPEATABILITY_ARTIFACT_PATH,
    MAX_STRUCTURED_OUTPUT_ATTEMPTS,
    REPEATABILITY_EXECUTION_ORDER,
    REPEATABILITY_LIVE_ENV_FLAG,
    REPEATABILITY_PLANNED_EXECUTIONS,
    build_production_semantic_assessor,
    build_repeatability_artifact,
    format_repeatability_report,
    repeatability_execution_matrix,
    run_repeatability_live_harness,
    run_repeatability_offline_harness,
    write_repeatability_artifact,
)


def _env_flag_enabled() -> bool:
    return os.environ.get(REPEATABILITY_LIVE_ENV_FLAG, "").strip().lower() in {
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


def _configuration_dict(config: ApplicationConfig | None) -> dict[str, object]:
    if config is None:
        return {
            "llm_model": None,
            "sufficiency_reasoning_effort": None,
            "sufficiency_max_output_tokens": None,
            "structured_output_max_attempts": MAX_STRUCTURED_OUTPUT_ATTEMPTS,
        }
    return {
        "llm_model": config.llm_model,
        "sufficiency_reasoning_effort": config.sufficiency_reasoning_effort,
        "sufficiency_max_output_tokens": config.sufficiency_max_output_tokens,
        "structured_output_max_attempts": MAX_STRUCTURED_OUTPUT_ATTEMPTS,
    }


def main() -> int:
    live_requested = _env_flag_enabled()
    matrix = repeatability_execution_matrix()

    print("=== P1-06 Semantic Sufficiency Repeatability Gate ===")
    print(f"{REPEATABILITY_LIVE_ENV_FLAG}={os.environ.get(REPEATABILITY_LIVE_ENV_FLAG, '')!r}")
    print(f"mode: {'live' if live_requested else 'offline (no provider)'}")
    print(f"execution_order: {' '.join(REPEATABILITY_EXECUTION_ORDER)}")
    print(f"planned_executions: {REPEATABILITY_PLANNED_EXECUTIONS}")
    print(
        "theoretical_max_llm_calls_if_all_retry_to_exhaustion: "
        f"{REPEATABILITY_PLANNED_EXECUTIONS * MAX_STRUCTURED_OUTPUT_ATTEMPTS}"
    )
    print(f"matrix_size: {len(matrix)}")
    print()

    config: ApplicationConfig | None = None
    if live_requested:
        config = ApplicationConfig.from_env()
        _print_config(config)
        assessor = build_production_semantic_assessor(config)
        executions = run_repeatability_live_harness(assessor)
        mode = "live"
        if len(executions) < REPEATABILITY_PLANNED_EXECUTIONS:
            skipped = REPEATABILITY_EXECUTION_ORDER[len(executions) :]
            print("=== Fail-fast stop ===")
            print(
                "Execution(s) skipped after failure (no provider call): "
                + ", ".join(skipped)
            )
            print()
    else:
        print("Offline mode: using fixture RawSemanticDecision (no provider call).")
        print()
        executions = run_repeatability_offline_harness()
        mode = "offline"

    artifact = build_repeatability_artifact(
        configuration=_configuration_dict(config),
        executions=executions,
        mode=mode,
        execution_order=REPEATABILITY_EXECUTION_ORDER,
    )
    artifact_path = write_repeatability_artifact(artifact)

    print(format_repeatability_report(artifact))
    print()
    print(f"artifact_path: {artifact_path}")
    print()

    print("=== Acceptance summary ===")
    for item in executions:
        status = "PASS" if item.acceptance.passed else "FAIL"
        print(f"{item.execution_id} ({item.result.scenario_id}): {status}")
        for failure in item.acceptance.failures:
            print(f"  - {failure}")
        if item.failure_classification:
            print(f"  failure_classification: {item.failure_classification}")

    print()
    print(f"acceptance_verdict: {artifact['acceptance_verdict']}")

    if not artifact["passed"]:
        print()
        print("STOP: repeatability gate failed; no automatic rerun.")
        return 1

    if live_requested and len(executions) == REPEATABILITY_PLANNED_EXECUTIONS:
        print()
        print("Repeatability gate completed: 6/6 executions accepted.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
