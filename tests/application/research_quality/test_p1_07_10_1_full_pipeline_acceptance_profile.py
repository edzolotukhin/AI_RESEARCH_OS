"""P1-07.10.1 offline contracts for the full-pipeline acceptance overlay."""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt

from application.config import ApplicationConfig
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    _current_stage,
    set_execution_stage,
    stage_for_executor,
)
from application.execution.execution_budget_factory import create_execution_budget
from application.research_quality.production_targeted_research_runner import (
    ProductionTargetedResearchRunner,
)
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient

from tests.application.research_quality.test_p1_07_10_full_pipeline_acceptance_profile_design import (
    PLANNER_WORST_CASE_CALLS,
    PROFILE_B,
    SERBIA_INFORMATION_NEEDS,
    SERBIA_RESEARCH_QUESTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OVERLAY_PATH = REPO_ROOT / "docker-compose.full-pipeline-acceptance.yml"
LOWCOST_PATH = REPO_ROOT / "docker-compose.lowcost.yml"
BASE_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DOC_PATH = (
    REPO_ROOT / "docs" / "acceptance" / "P1-07.10.1-Full-Pipeline-Acceptance-Profile-Implementation.md"
)
DESIGN_DOC_PATH = (
    REPO_ROOT / "docs" / "acceptance" / "P1-07.10-Full-Pipeline-Acceptance-Profile-Design.md"
)

PROFILE_B_WORKER = {
    "LLM_MAX_CALLS_PER_RUN": "120",
    "EVIDENCE_MAX_LLM_CALLS": "36",
    "EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS": "6",
    "SUFFICIENCY_MAX_LLM_CALLS": "36",
    "ANALYSIS_MAX_LLM_CALLS": "10",
    "REPORT_MAX_LLM_CALLS": "12",
    "REVIEW_MAX_CALLS": "3",
    "SOURCE_MAX_CANDIDATES_PER_QUERY": "3",
    "SOURCE_MAX_CANDIDATES_PER_INFORMATION_NEED": "3",
    "SOURCE_MAX_SOURCES_PER_RUN": "18",
    "SOURCE_MIN_SUCCESSFUL_SOURCES": "3",
    "SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO": "1.0",
    "RESEARCH_MAX_GAP_ROUNDS_PER_RUN": "2",
    "TARGETED_MAX_ATTEMPTS_PER_GAP": "2",
    "TARGETED_MAX_QUERIES_PER_GAP": "1",
    "TARGETED_MAX_SOURCES_PER_GAP": "1",
}
PROFILE_B_API = {
    "SOURCE_MAX_CANDIDATES_PER_QUERY": "3",
    "SOURCE_MAX_CANDIDATES_PER_INFORMATION_NEED": "3",
    "SOURCE_MAX_SOURCES_PER_RUN": "18",
    "SOURCE_MIN_SUCCESSFUL_SOURCES": "3",
    "SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO": "1.0",
}
FORBIDDEN_OVERRIDE_KEYS = {
    "LLM_MODEL",
    "SEARCH_PROVIDER",
    "EVIDENCE_EXTRACTOR",
    "ANALYSIS_ENGINE",
    "REPORT_ENGINE",
    "REVIEW_ENGINE",
    "PLANNER_REASONING_EFFORT",
    "PLANNER_MAX_OUTPUT_TOKENS",
    "PLANNER_SEMANTIC_MAX_ATTEMPTS",
    "ANALYSIS_REASONING_EFFORT",
    "ANALYSIS_MAX_OUTPUT_TOKENS",
    "REPORT_REASONING_EFFORT",
    "REPORT_MAX_OUTPUT_TOKENS",
    "REVIEW_REASONING_EFFORT",
    "REVIEW_MAX_OUTPUT_TOKENS",
    "REVIEW_STRUCTURED_OUTPUT_MAX_ATTEMPTS",
    "REPORT_MAX_RQ_CORRECTION_ATTEMPTS",
    "EVIDENCE_REASONING_EFFORT",
    "SUFFICIENCY_REASONING_EFFORT",
    "EVIDENCE_MAX_ITEMS_PER_SOURCE",
}


def _service_env_block(text: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-z]|\Z)",
        text,
    )
    if match is None:
        raise AssertionError(f"service {service!r} not found")
    return match.group(1)


def _env_from_overlay_service(text: str, service: str) -> dict[str, str]:
    block = _service_env_block(text, service)
    return dict(re.findall(r'^\s+([A-Z][A-Z0-9_]+):\s*"([^"]*)"', block, flags=re.M))


def _normalize_compose_env(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        parsed: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key] = value
        return parsed
    raise AssertionError(f"unexpected compose environment type: {type(raw)!r}")


def _merged_compose_config() -> dict:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.full-pipeline-acceptance.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest(
            "docker compose config unavailable: "
            + (completed.stderr or completed.stdout or str(completed.returncode)),
        )
    return json.loads(completed.stdout)


def _profile_b_budget() -> ExecutionBudget:
    return ExecutionBudget(
        evidence_max_llm_calls=PROFILE_B.evidence_max_llm_calls,
        sufficiency_max_llm_calls=PROFILE_B.sufficiency_max_llm_calls,
        analysis_max_llm_calls=PROFILE_B.analysis_max_llm_calls,
        report_max_llm_calls=PROFILE_B.report_max_llm_calls,
        review_max_llm_calls=PROFILE_B.review_max_calls,
        llm_max_calls_per_run=PROFILE_B.llm_max_calls_per_run,
    )


class OverlayPresenceAndLowcostTests(unittest.TestCase):
    def test_a_overlay_exists(self) -> None:
        self.assertTrue(OVERLAY_PATH.is_file())

    def test_b_lowcost_unchanged(self) -> None:
        lowcost = LOWCOST_PATH.read_text(encoding="utf-8")
        self.assertIn('SOURCE_MAX_SOURCES_PER_RUN: "5"', lowcost)
        self.assertIn('LLM_MAX_CALLS_PER_RUN: "24"', lowcost)
        self.assertIn('EVIDENCE_MAX_LLM_CALLS: "8"', lowcost)
        self.assertIn('SUFFICIENCY_MAX_LLM_CALLS: "6"', lowcost)
        self.assertIn('ANALYSIS_MAX_LLM_CALLS: "2"', lowcost)
        self.assertIn('REPORT_MAX_LLM_CALLS: "2"', lowcost)
        self.assertIn('REVIEW_MAX_CALLS: "1"', lowcost)
        self.assertIn('RESEARCH_MAX_GAP_ROUNDS_PER_RUN: "1"', lowcost)
        self.assertIn('TARGETED_MAX_ATTEMPTS_PER_GAP: "1"', lowcost)
        self.assertNotIn("EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS", lowcost)

    def test_c_profile_b_values_present(self) -> None:
        text = OVERLAY_PATH.read_text(encoding="utf-8")
        worker = _env_from_overlay_service(text, "worker")
        api = _env_from_overlay_service(text, "api")
        self.assertEqual(worker, PROFILE_B_WORKER)
        self.assertEqual(api, PROFILE_B_API)
        self.assertEqual(int(worker["SOURCE_MAX_SOURCES_PER_RUN"]), PROFILE_B.source_max_sources_per_run)
        self.assertEqual(int(worker["EVIDENCE_MAX_LLM_CALLS"]), PROFILE_B.evidence_max_llm_calls)
        self.assertEqual(int(worker["LLM_MAX_CALLS_PER_RUN"]), PROFILE_B.llm_max_calls_per_run)


class ComposeMergeAndConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.merged = _merged_compose_config()

    def test_d_base_plus_acceptance_merge(self) -> None:
        services = self.merged["services"]
        self.assertIn("api", services)
        self.assertIn("worker", services)
        worker = _normalize_compose_env(services["worker"]["environment"])
        api = _normalize_compose_env(services["api"]["environment"])
        for key, expected in PROFILE_B_WORKER.items():
            self.assertEqual(worker[key], expected, msg=key)
        for key, expected in PROFILE_B_API.items():
            self.assertEqual(api[key], expected, msg=key)

    def test_e_worker_receives_stage_and_global_budgets(self) -> None:
        worker = _normalize_compose_env(self.merged["services"]["worker"]["environment"])
        self.assertEqual(worker["LLM_MAX_CALLS_PER_RUN"], "120")
        self.assertEqual(worker["EVIDENCE_MAX_LLM_CALLS"], "36")
        self.assertEqual(worker["EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS"], "6")
        self.assertEqual(worker["SUFFICIENCY_MAX_LLM_CALLS"], "36")
        self.assertEqual(worker["ANALYSIS_MAX_LLM_CALLS"], "10")
        self.assertEqual(worker["REPORT_MAX_LLM_CALLS"], "12")
        self.assertEqual(worker["REVIEW_MAX_CALLS"], "3")

    def test_f_api_worker_source_settings_agree(self) -> None:
        worker = _normalize_compose_env(self.merged["services"]["worker"]["environment"])
        api = _normalize_compose_env(self.merged["services"]["api"]["environment"])
        for key in PROFILE_B_API:
            self.assertEqual(api[key], worker[key], msg=key)

    def test_g_coverage_ratio_remains_one(self) -> None:
        worker = _normalize_compose_env(self.merged["services"]["worker"]["environment"])
        api = _normalize_compose_env(self.merged["services"]["api"]["environment"])
        self.assertEqual(worker["SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO"], "1.0")
        self.assertEqual(api["SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO"], "1.0")


class ReasoningRetryAndQualityInvariantTests(unittest.TestCase):
    def test_h_evidence_reasoning_remains_minimal_by_default(self) -> None:
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("EVIDENCE_REASONING_EFFORT", overlay)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVIDENCE_REASONING_EFFORT", None)
            config = ApplicationConfig.from_env()
        self.assertEqual(config.evidence_reasoning_effort, "minimal")

    def test_i_no_retry_token_model_provider_override(self) -> None:
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        for key in FORBIDDEN_OVERRIDE_KEYS:
            self.assertNotIn(key, overlay)
        base = BASE_COMPOSE_PATH.read_text(encoding="utf-8")
        self.assertIn("LLM_MODEL: ${LLM_MODEL:-gpt-5}", base)
        self.assertIn("SEARCH_PROVIDER: ${SEARCH_PROVIDER:-tavily}", base)

    def test_j_readiness_all_in_rule_unchanged(self) -> None:
        assessments = []
        for index in range(1, 13):
            count = 0 if index == 12 else 2
            semantic = None
            if count:
                semantic = SemanticSufficiencyAssessment(
                    status=SufficiencyStatus.SUFFICIENT,
                    confidence=0.7,
                    reason="offline",
                )
            assessments.append(
                build_information_need_assessment(
                    signals=DeterministicSufficiencySignals(
                        information_need_id=f"IN{index}",
                        research_question_id="RQ1",
                        evidence_count=count,
                        independent_source_count=1 if count else 0,
                        evidence_ids=tuple(f"e-{index}-{n}" for n in range(count)),
                        source_ids=("src-1",) if count else (),
                    ),
                    semantic=semantic,
                ),
            )
        result = build_research_readiness_result(
            (
                build_research_readiness_assessment(
                    research_question_id="RQ1",
                    need_assessments=tuple(assessments),
                ),
            ),
        )
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("IN12", result.blocking_information_need_ids)

    def test_k_targeted_research_values(self) -> None:
        worker = _env_from_overlay_service(OVERLAY_PATH.read_text(encoding="utf-8"), "worker")
        self.assertEqual(worker["RESEARCH_MAX_GAP_ROUNDS_PER_RUN"], "2")
        self.assertEqual(worker["TARGETED_MAX_ATTEMPTS_PER_GAP"], "2")
        self.assertEqual(worker["TARGETED_MAX_QUERIES_PER_GAP"], "1")
        self.assertEqual(worker["TARGETED_MAX_SOURCES_PER_GAP"], "1")

    def test_l_targeted_evidence_shares_evidence_cap(self) -> None:
        source = inspect.getsource(ProductionTargetedResearchRunner.run)
        self.assertIn("extract_for_source_ids", source)
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("TARGETED_EVIDENCE_MAX_LLM_CALLS", overlay)
        self.assertNotIn("TARGETED_MAX_LLM_CALLS", overlay)
        extraction = (
            REPO_ROOT / "application" / "evidence" / "evidence_extraction_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn('assert_can_call("evidence"', extraction)


class BudgetReserveAndDownstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._budget_token = _current_budget.set(None)
        self._stage_token = _current_stage.set(None)
        self.addCleanup(_current_budget.reset, self._budget_token)
        self.addCleanup(_current_stage.reset, self._stage_token)

    def test_m_global_and_downstream_reserve_allow_full_stage_caps(self) -> None:
        budget = _profile_b_budget()
        downstream_from_evidence = (
            budget.sufficiency_max_llm_calls
            + budget.analysis_max_llm_calls
            + budget.report_max_llm_calls
            + budget.review_max_llm_calls
        )
        self.assertEqual(downstream_from_evidence, 61)
        allowed_before_reserve = budget.llm_max_calls_per_run - downstream_from_evidence
        self.assertEqual(allowed_before_reserve, 59)
        self.assertGreaterEqual(
            allowed_before_reserve,
            PLANNER_WORST_CASE_CALLS + budget.evidence_max_llm_calls,
        )

        set_execution_stage("planner")
        for _ in range(PLANNER_WORST_CASE_CALLS):
            budget.assert_can_call("planner")
            budget.record_llm_call("planner")
        set_execution_stage("evidence")
        for _ in range(budget.evidence_max_llm_calls):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        self.assertTrue(budget.stage_cap_reached("evidence"))
        self.assertFalse(budget.exhausted)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, "evidence_max_llm_calls")

        set_execution_stage("sufficiency")
        for _ in range(budget.sufficiency_max_llm_calls):
            budget.assert_can_call("sufficiency")
            budget.record_llm_call("sufficiency")
        self.assertTrue(budget.stage_cap_reached("sufficiency"))
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("sufficiency")
        self.assertEqual(ctx.exception.reason, "sufficiency_max_llm_calls")

        set_execution_stage("analysis")
        budget.assert_can_call("analysis")
        budget.record_llm_call("analysis")
        self.assertEqual(budget.stage_calls("analysis"), 1)

        envelope = (
            PLANNER_WORST_CASE_CALLS
            + budget.evidence_max_llm_calls
            + budget.sufficiency_max_llm_calls
            + budget.analysis_max_llm_calls
            + budget.report_max_llm_calls
            + budget.review_max_llm_calls
        )
        self.assertEqual(envelope, 106)
        self.assertGreater(budget.llm_max_calls_per_run, envelope)

    def test_m_factory_maps_overlay_env_to_execution_budget(self) -> None:
        env = {
            "LLM_MAX_CALLS_PER_RUN": "120",
            "EVIDENCE_MAX_LLM_CALLS": "36",
            "EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS": "6",
            "SUFFICIENCY_MAX_LLM_CALLS": "36",
            "ANALYSIS_MAX_LLM_CALLS": "10",
            "REPORT_MAX_LLM_CALLS": "12",
            "REVIEW_MAX_CALLS": "3",
        }
        with patch.dict(os.environ, env, clear=False):
            budget = create_execution_budget(ApplicationConfig.from_env())
        self.assertEqual(budget.llm_max_calls_per_run, 120)
        self.assertEqual(budget.evidence_max_llm_calls, 36)
        self.assertEqual(budget.evidence_remediation_reserved_llm_calls, 6)
        self.assertEqual(budget.evidence_initial_allowance, 30)
        self.assertEqual(budget.sufficiency_max_llm_calls, 36)
        self.assertEqual(budget.analysis_max_llm_calls, 10)
        self.assertEqual(budget.report_max_llm_calls, 12)
        self.assertEqual(budget.review_max_llm_calls, 3)

    def test_m_preexisting_isolation_case_is_not_profile_b(self) -> None:
        productish = ExecutionBudget(
            llm_max_calls_per_run=100,
            evidence_max_llm_calls=50,
            analysis_max_llm_calls=14,
        )
        reserve = (
            productish.sufficiency_max_llm_calls
            + productish.analysis_max_llm_calls
            + productish.report_max_llm_calls
            + productish.review_max_llm_calls
        )
        self.assertEqual(reserve, 61)
        self.assertLess(100 - reserve, 50)
        profile_b = _profile_b_budget()
        profile_reserve = (
            profile_b.sufficiency_max_llm_calls
            + profile_b.analysis_max_llm_calls
            + profile_b.report_max_llm_calls
            + profile_b.review_max_llm_calls
        )
        self.assertGreaterEqual(120 - profile_reserve, profile_b.evidence_max_llm_calls)

    def test_n_analysis_report_review_support_six_rq_happy_path(self) -> None:
        analysis_happy = SERBIA_RESEARCH_QUESTIONS + 1
        report_happy = SERBIA_RESEARCH_QUESTIONS + 1
        review_first_attempt = 1
        self.assertGreaterEqual(PROFILE_B.analysis_max_llm_calls, analysis_happy)
        self.assertGreaterEqual(PROFILE_B.report_max_llm_calls, report_happy)
        self.assertGreaterEqual(PROFILE_B.review_max_calls, review_first_attempt)
        self.assertGreaterEqual(
            PROFILE_B.review_max_calls,
            3,
            msg="structured-output default max_attempts=3 on one review batch",
        )
        self.assertGreaterEqual(
            PROFILE_B.sufficiency_max_llm_calls,
            SERBIA_INFORMATION_NEEDS * (1 + PROFILE_B.intended_targeted_reevals),
        )

    def test_targeted_generate_during_readiness_uses_active_stage(self) -> None:
        budget = _profile_b_budget()
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok", output_tokens=1)
        client = BudgetEnforcingLLMClient(mock)
        token = _current_budget.set(budget)
        try:
            set_execution_stage("evidence")
            client.generate(Prompt(system="s", user="u"))
            self.assertEqual(stage_for_executor("research_quality"), "sufficiency")
            set_execution_stage(stage_for_executor("research_quality"))
            client.generate(Prompt(system="s", user="u"))
        finally:
            _current_budget.reset(token)
        self.assertEqual(budget.stage_calls("evidence"), 1)
        self.assertEqual(budget.stage_calls("sufficiency"), 1)

    def test_evidence_precheck_still_gates_targeted_extract(self) -> None:
        service_source = (
            REPO_ROOT / "application" / "evidence" / "evidence_extraction_service.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(service_source)
        names = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("assert_can_call", names)
        self.assertIn('assert_can_call("evidence"', service_source)


class OwnershipAndInvocationTests(unittest.TestCase):
    def test_o_distinct_documented_purposes(self) -> None:
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        doc = DOC_PATH.read_text(encoding="utf-8")
        design = DESIGN_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("diagnostic / cost-bounded", overlay)
        self.assertIn("full-pipeline acceptance", overlay)
        self.assertIn("NOT a production default", overlay)
        self.assertIn("docker-compose.lowcost.yml", doc)
        self.assertIn("diagnostic", doc.lower())
        self.assertIn("full-pipeline acceptance", doc.lower())
        self.assertIn("Profile B", design)

    def test_p_invocation_is_base_plus_acceptance_not_lowcost_stack(self) -> None:
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        doc = DOC_PATH.read_text(encoding="utf-8")
        intended = (
            "docker compose -f docker-compose.yml "
            "-f docker-compose.full-pipeline-acceptance.yml"
        )
        self.assertIn("do NOT stack on lowcost", overlay)
        self.assertIn(intended, overlay)
        self.assertIn(intended, doc)
        self.assertIn("do not stack", doc.lower())
        positive_lines = [
            line
            for line in f"{overlay}\n{doc}".splitlines()
            if intended in line and "NOT" not in line.upper()
        ]
        self.assertTrue(positive_lines)
        for line in positive_lines:
            self.assertNotIn("lowcost", line)


if __name__ == "__main__":
    unittest.main()
