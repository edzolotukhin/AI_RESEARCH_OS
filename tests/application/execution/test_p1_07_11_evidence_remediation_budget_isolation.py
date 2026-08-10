"""P1-07.11 Evidence remediation budget isolation."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from domain.ai.prompt import Prompt
from domain.ai.llm_response import LLMResponse

from application.config import ApplicationConfig
from application.execution.budget_utils import (
    EVIDENCE_INITIAL_PARTITION_REASON,
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    _current_evidence_purpose,
    _current_stage,
    set_evidence_call_purpose,
    set_execution_stage,
)
from application.execution.execution_budget_factory import create_execution_budget
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient


class EvidenceRemediationPartitionTests(unittest.TestCase):
    def test_default_reserved_is_zero_and_matches_legacy_total_envelope(self) -> None:
        budget = ExecutionBudget(evidence_max_llm_calls=50)
        self.assertEqual(budget.evidence_remediation_reserved, 0)
        self.assertEqual(budget.evidence_initial_allowance, 50)
        for _ in range(50):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, EVIDENCE_STAGE_CAP_REASON)

    def test_initial_cannot_consume_remediation_reserve(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=36,
            evidence_remediation_reserved_llm_calls=6,
        )
        self.assertEqual(budget.evidence_initial_allowance, 30)
        for _ in range(30):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, EVIDENCE_INITIAL_PARTITION_REASON)
        self.assertEqual(budget.stage_calls("evidence"), 30)
        self.assertFalse(budget.evidence_total_cap_reached())
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)

    def test_targeted_can_consume_remediation_reserve_and_leftover_initial(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=36,
            evidence_remediation_reserved_llm_calls=6,
        )
        for _ in range(20):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        for _ in range(16):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(budget.evidence_initial_calls, 20)
        self.assertEqual(budget.evidence_remediation_calls, 16)
        self.assertEqual(budget.stage_calls("evidence"), 36)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(ctx.exception.reason, EVIDENCE_REMEDIATION_BUDGET_REASON)

    def test_targeted_cannot_exceed_total_evidence_envelope(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=36,
            evidence_remediation_reserved_llm_calls=6,
        )
        for _ in range(30):
            budget.record_llm_call("evidence")
        for _ in range(6):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(ctx.exception.reason, EVIDENCE_REMEDIATION_BUDGET_REASON)

    def test_non_targeted_path_cannot_claim_targeted_allowance(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=10,
            evidence_remediation_reserved_llm_calls=3,
        )
        for _ in range(7):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence")
        self.assertEqual(budget.evidence_remediation_calls, 0)
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)

    def test_global_cap_still_enforced_for_remediation(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=5,
            evidence_max_llm_calls=50,
            evidence_remediation_reserved_llm_calls=10,
            sufficiency_max_llm_calls=0,
            analysis_max_llm_calls=0,
            report_max_llm_calls=0,
            review_max_llm_calls=0,
        )
        for _ in range(5):
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(ctx.exception.reason, "llm_max_calls_per_run")

    def test_downstream_reserve_still_enforced_for_initial_evidence(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=100,
            evidence_max_llm_calls=50,
            evidence_remediation_reserved_llm_calls=0,
        )
        allowed = 100 - (20 + 14 + 20 + 7)
        for _ in range(allowed):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, "downstream_reserve_exhausted")

    def test_remediation_uses_sufficiency_level_downstream_reserve(self) -> None:
        budget = ExecutionBudget(
            llm_max_calls_per_run=120,
            evidence_max_llm_calls=36,
            evidence_remediation_reserved_llm_calls=6,
            sufficiency_max_llm_calls=36,
            analysis_max_llm_calls=10,
            report_max_llm_calls=12,
            review_max_llm_calls=3,
        )
        for _ in range(30):
            budget.record_llm_call("evidence")
        for _ in range(36):
            budget.record_llm_call("sufficiency")
        # total 66; sufficiency-level reserve is 10+12+3=25 → allowed before=95
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.assertEqual(budget.evidence_remediation_calls, 1)

    def test_config_default_and_from_env(self) -> None:
        self.assertEqual(ApplicationConfig().evidence_remediation_reserved_llm_calls, 0)
        self.assertEqual(
            ApplicationConfig().evidence_remediation_max_llm_calls_per_attempt,
            0,
        )
        env = {"EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS": "6", "EVIDENCE_MAX_LLM_CALLS": "36"}
        with patch.dict(os.environ, env, clear=False):
            config = ApplicationConfig.from_env()
            budget = create_execution_budget(config)
        self.assertEqual(config.evidence_remediation_reserved_llm_calls, 6)
        self.assertEqual(budget.evidence_initial_allowance, 30)

    def test_lowcost_without_key_keeps_full_initial_envelope(self) -> None:
        env = {
            "LLM_MAX_CALLS_PER_RUN": "24",
            "EVIDENCE_MAX_LLM_CALLS": "8",
            "SUFFICIENCY_MAX_LLM_CALLS": "6",
            "ANALYSIS_MAX_LLM_CALLS": "2",
            "REPORT_MAX_LLM_CALLS": "2",
            "REVIEW_MAX_CALLS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS", None)
            budget = create_execution_budget(ApplicationConfig.from_env())
        self.assertEqual(budget.evidence_remediation_reserved, 0)
        self.assertEqual(budget.evidence_initial_allowance, 8)

    def test_budget_enforcing_client_remaps_remediation_purpose_to_evidence(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=10,
            evidence_remediation_reserved_llm_calls=4,
            sufficiency_max_llm_calls=20,
        )
        mock = Mock()
        mock.generate.return_value = LLMResponse(content="ok", output_tokens=1)
        client = BudgetEnforcingLLMClient(mock)
        token_b = _current_budget.set(budget)
        token_s = _current_stage.set("sufficiency")
        token_p = _current_evidence_purpose.set(None)
        try:
            set_execution_stage("sufficiency")
            set_evidence_call_purpose(EVIDENCE_PURPOSE_REMEDIATION)
            client.generate(Prompt(system="s", user="u"))
        finally:
            _current_budget.reset(token_b)
            _current_stage.reset(token_s)
            _current_evidence_purpose.reset(token_p)
        self.assertEqual(budget.stage_calls("evidence"), 1)
        self.assertEqual(budget.evidence_remediation_calls, 1)
        self.assertEqual(budget.stage_calls("sufficiency"), 0)
