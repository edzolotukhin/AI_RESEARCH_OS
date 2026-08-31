from __future__ import annotations

import time

from application.execution.budget_utils import EVIDENCE_PURPOSE_REMEDIATION
from application.execution.execution_budget_context import (
    get_evidence_call_purpose,
    get_execution_budget,
    get_execution_stage,
)
from application.execution.remediation_attempt_envelope import (
    RemediationAttemptEnvelopeReached,
    remediations_attempt_envelope_blocks_call,
)
from application.execution.execution_budget_retry import (
    consume_llm_call_retry_flag,
)
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient


class BudgetEnforcingLLMClient(LLMClient):
    """Records and enforces per-run LLM budgets for workflow-scoped execution."""

    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate

    def generate(
        self,
        prompt: Prompt,
        *,
        options: LLMGenerationOptions | None = None,
    ):
        budget = get_execution_budget()
        if budget is None:
            return self._delegate.generate(prompt, options=options)

        purpose = get_evidence_call_purpose()
        stage = get_execution_stage() or "unknown"
        if purpose == EVIDENCE_PURPOSE_REMEDIATION:
            stage = "evidence"
        if remediations_attempt_envelope_blocks_call(budget, purpose=purpose):
            raise RemediationAttemptEnvelopeReached()
        budget.assert_can_call(stage, purpose=purpose)

        started = time.perf_counter()
        try:
            response = self._delegate.generate(prompt, options=options)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            budget.record_llm_call(
                stage,
                purpose=purpose,
                input_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                elapsed_ms=elapsed_ms,
                retry=consume_llm_call_retry_flag(),
            )
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        budget.record_llm_call(
            stage,
            purpose=purpose,
            input_tokens=0,
            output_tokens=response.output_tokens or 0,
            reasoning_tokens=response.reasoning_tokens or 0,
            elapsed_ms=elapsed_ms,
            retry=consume_llm_call_retry_flag(),
        )
        return response
