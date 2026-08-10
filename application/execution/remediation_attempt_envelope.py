"""Per-remediation-attempt Evidence LLM envelope (P1-07.16.1).

A local stop condition inside the existing remediations stage reserve.
Does not copy or expand ExecutionBudget. Actual Evidence stage LLM calls
remain the billing source of truth.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from application.execution.budget_utils import EVIDENCE_PURPOSE_REMEDIATION
from application.execution.execution_budget import ExecutionBudget

EXTRACTION_FULLY_PROCESSED = "fully_processed"
EXTRACTION_BOUNDED_PARTIAL = "bounded_partial"
EXTRACTION_ORDERING_DOCUMENT_ORDER = "document_order"
SHARED_REMEDIATION_EXTRACTION_KEY = "remediation_extraction"


class RemediationAttemptEnvelopeReached(Exception):
    """Local remediations-attempt Evidence envelope reached.

    This is not global stage budget exhaustion.
    """


@dataclass(frozen=True)
class RemediationAttemptEnvelope:
    configured_limit: int
    effective_limit: int
    evidence_stage_calls_at_start: int
    remediations_reserved_remaining_at_start: int

    def actual_evidence_calls_consumed(self, budget: ExecutionBudget) -> int:
        return max(0, budget.stage_calls("evidence") - self.evidence_stage_calls_at_start)

    def reached(self, budget: ExecutionBudget) -> bool:
        if self.effective_limit <= 0:
            return True
        return self.actual_evidence_calls_consumed(budget) >= self.effective_limit


_current_envelope: ContextVar[RemediationAttemptEnvelope | None] = ContextVar(
    "remediation_attempt_envelope",
    default=None,
)


def remediations_callable_capacity(budget: ExecutionBudget) -> int:
    total_room = max(0, budget.evidence_max_llm_calls - budget.stage_calls("evidence"))
    leftover_initial = max(
        0,
        budget.evidence_initial_allowance - budget.evidence_initial_calls,
    )
    reserved_remaining = remediations_reserved_remaining(budget)
    return min(total_room, leftover_initial + reserved_remaining)


def remediations_reserved_remaining(budget: ExecutionBudget) -> int:
    return max(
        0,
        budget.evidence_remediation_reserved - budget.evidence_remediation_calls,
    )


def build_remediation_attempt_envelope(
    *,
    configured_limit: int,
    budget: ExecutionBudget | None,
) -> RemediationAttemptEnvelope | None:
    if configured_limit <= 0 or budget is None:
        return None
    remaining = remediations_callable_capacity(budget)
    return RemediationAttemptEnvelope(
        configured_limit=configured_limit,
        effective_limit=min(configured_limit, remaining),
        evidence_stage_calls_at_start=budget.stage_calls("evidence"),
        remediations_reserved_remaining_at_start=remediations_reserved_remaining(budget),
    )


def activate_remediation_attempt_envelope(envelope: RemediationAttemptEnvelope):
    return _current_envelope.set(envelope)


def reset_remediation_attempt_envelope(token) -> None:
    _current_envelope.reset(token)


def get_remediation_attempt_envelope() -> RemediationAttemptEnvelope | None:
    return _current_envelope.get()


def remediations_attempt_envelope_blocks_call(
    budget: ExecutionBudget | None,
    *,
    purpose: str | None,
) -> bool:
    if budget is None or purpose != EVIDENCE_PURPOSE_REMEDIATION:
        return False
    envelope = get_remediation_attempt_envelope()
    if envelope is None:
        return False
    return envelope.reached(budget)
