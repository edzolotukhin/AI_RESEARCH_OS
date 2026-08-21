from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.execution.budget_utils import (
    EVIDENCE_INITIAL_PARTITION_REASON,
    EVIDENCE_PURPOSE_INITIAL,
    EVIDENCE_PURPOSE_REMEDIATION,
    EVIDENCE_REMEDIATION_BUDGET_REASON,
    EVIDENCE_STAGE_CAP_REASON,
)
from application.execution.exceptions import BudgetExhaustedError

_STAGE_LLM_CALL_LIMITS: dict[str, str] = {
    "evidence": "evidence_max_llm_calls",
    "sufficiency": "sufficiency_max_llm_calls",
    "analysis": "analysis_max_llm_calls",
    "report": "report_max_llm_calls",
    "review": "review_max_llm_calls",
    "quant_findings": "quant_findings_max_llm_calls",
    "quant_insights": "quant_insights_max_llm_calls",
    "quant_report": "quant_report_max_llm_calls",
}


@dataclass
class StageBudgetUsage:
    stage: str
    llm_calls: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    elapsed_ms: int = 0
    stage_cap_reached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "llm_calls": self.llm_calls,
            "retries": self.retries,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "elapsed_ms": self.elapsed_ms,
            "stage_cap_reached": self.stage_cap_reached,
        }


@dataclass
class ExecutionBudget:
    evidence_max_items_per_run: int = 500
    evidence_max_items_per_source: int = 50
    analysis_max_findings: int = 100
    analysis_max_insights: int = 30
    report_max_sections: int = 12
    evidence_max_llm_calls: int = 50
    evidence_remediation_reserved_llm_calls: int = 0
    sufficiency_max_llm_calls: int = 20
    analysis_max_llm_calls: int = 14
    report_max_llm_calls: int = 20
    review_max_llm_calls: int = 7
    quant_findings_max_llm_calls: int = 1
    quant_insights_max_llm_calls: int = 1
    quant_report_max_llm_calls: int = 1
    llm_max_calls_per_run: int = 100
    max_input_tokens_per_run: int | None = None
    max_output_tokens_per_run: int | None = None

    _stage_usage: dict[str, StageBudgetUsage] = field(default_factory=dict, repr=False)
    _total_llm_calls: int = 0
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    _evidence_initial_calls: int = 0
    _evidence_remediation_calls: int = 0
    _exhausted: bool = False
    _exhaustion_reason: str | None = None
    _exhaustion_stage: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "quant_findings_max_llm_calls",
            "quant_insights_max_llm_calls",
            "quant_report_max_llm_calls",
        ):
            value = getattr(self, name)
            if value not in {0, 1}:
                raise ValueError(f"{name} must be zero or one")

    @property
    def evidence_remediation_reserved(self) -> int:
        reserved = max(0, self.evidence_remediation_reserved_llm_calls)
        return min(reserved, max(0, self.evidence_max_llm_calls))

    @property
    def evidence_initial_allowance(self) -> int:
        return max(0, self.evidence_max_llm_calls - self.evidence_remediation_reserved)

    @property
    def evidence_initial_calls(self) -> int:
        return self._evidence_initial_calls

    @property
    def evidence_remediation_calls(self) -> int:
        return self._evidence_remediation_calls

    def evidence_total_cap_reached(self) -> bool:
        return self.stage_calls("evidence") >= self.evidence_max_llm_calls

    def evidence_initial_partition_reached(self) -> bool:
        return self._evidence_initial_calls >= self.evidence_initial_allowance

    def stage_calls(self, stage: str) -> int:
        usage = self._stage_usage.get(stage)
        return usage.llm_calls if usage is not None else 0

    def stage_cap_limit(self, stage: str) -> int | None:
        attr = _STAGE_LLM_CALL_LIMITS.get(stage)
        if attr is None:
            return None
        return getattr(self, attr)

    def stage_cap_reached(self, stage: str) -> bool:
        usage = self._stage_usage.get(stage)
        if usage is not None and usage.stage_cap_reached:
            return True
        limit = self.stage_cap_limit(stage)
        if limit is None:
            return False
        return self.stage_calls(stage) >= limit

    def _downstream_reserve_required(
        self,
        stage: str,
        *,
        purpose: str | None = None,
    ) -> int:
        """Reserve capacity for stages that have not run yet."""
        reserve = 0
        resolved_purpose = purpose or EVIDENCE_PURPOSE_INITIAL
        # Targeted extract runs inside readiness: protect A/R/V only.
        if stage == "evidence" and resolved_purpose == EVIDENCE_PURPOSE_REMEDIATION:
            stage = "sufficiency"
        if stage in {"planner", "search", "evidence"}:
            reserve += self.sufficiency_max_llm_calls
            reserve += self.analysis_max_llm_calls
            reserve += self.report_max_llm_calls
            reserve += self.review_max_llm_calls
        elif stage == "sufficiency":
            reserve += self.analysis_max_llm_calls
            reserve += self.report_max_llm_calls
            reserve += self.review_max_llm_calls
        elif stage == "analysis":
            reserve += self.report_max_llm_calls
            reserve += self.review_max_llm_calls
        elif stage == "report":
            reserve += self.review_max_llm_calls
        return reserve

    def assert_can_call(self, stage: str, *, purpose: str | None = None) -> None:
        """Fail before issuing another LLM call when a limit is already reached."""
        if self._exhausted:
            raise BudgetExhaustedError(
                self._exhaustion_reason or "budget_exhausted",
                stage=stage,
            )

        reserve = self._downstream_reserve_required(stage, purpose=purpose)
        if reserve > 0:
            allowed_before_downstream_cap = self.llm_max_calls_per_run - reserve
            if (
                allowed_before_downstream_cap >= 0
                and self._total_llm_calls >= allowed_before_downstream_cap
            ):
                raise BudgetExhaustedError("downstream_reserve_exhausted", stage=stage)
        if self._total_llm_calls >= self.llm_max_calls_per_run:
            raise BudgetExhaustedError("llm_max_calls_per_run", stage=stage)

        if stage == "evidence":
            self._assert_can_call_evidence(purpose=purpose)
            return
        stage_calls = self.stage_calls(stage)
        if stage == "sufficiency" and stage_calls >= self.sufficiency_max_llm_calls:
            raise BudgetExhaustedError("sufficiency_max_llm_calls", stage=stage)
        if stage == "analysis" and stage_calls >= self.analysis_max_llm_calls:
            raise BudgetExhaustedError("analysis_max_llm_calls", stage=stage)
        if stage == "report" and stage_calls >= self.report_max_llm_calls:
            raise BudgetExhaustedError("report_max_llm_calls", stage=stage)
        if stage == "review" and stage_calls >= self.review_max_llm_calls:
            raise BudgetExhaustedError("review_max_llm_calls", stage=stage)
        if stage == "quant_findings" and stage_calls >= self.quant_findings_max_llm_calls:
            raise BudgetExhaustedError("quant_findings_max_llm_calls", stage=stage)
        if stage == "quant_insights" and stage_calls >= self.quant_insights_max_llm_calls:
            raise BudgetExhaustedError("quant_insights_max_llm_calls", stage=stage)
        if stage == "quant_report" and stage_calls >= self.quant_report_max_llm_calls:
            raise BudgetExhaustedError("quant_report_max_llm_calls", stage=stage)

    def _assert_can_call_evidence(self, *, purpose: str | None) -> None:
        resolved = purpose or EVIDENCE_PURPOSE_INITIAL
        total = self.stage_calls("evidence")
        if resolved == EVIDENCE_PURPOSE_INITIAL:
            if self._evidence_initial_calls >= self.evidence_initial_allowance:
                reason = (
                    EVIDENCE_INITIAL_PARTITION_REASON
                    if self.evidence_remediation_reserved > 0
                    else EVIDENCE_STAGE_CAP_REASON
                )
                raise BudgetExhaustedError(reason, stage="evidence")
            if total >= self.evidence_max_llm_calls:
                raise BudgetExhaustedError(EVIDENCE_STAGE_CAP_REASON, stage="evidence")
            return
        if resolved == EVIDENCE_PURPOSE_REMEDIATION:
            if total >= self.evidence_max_llm_calls:
                reason = (
                    EVIDENCE_REMEDIATION_BUDGET_REASON
                    if self.evidence_remediation_reserved > 0
                    else EVIDENCE_STAGE_CAP_REASON
                )
                raise BudgetExhaustedError(reason, stage="evidence")
            leftover_initial = max(
                0,
                self.evidence_initial_allowance - self._evidence_initial_calls,
            )
            reserved_remaining = max(
                0,
                self.evidence_remediation_reserved - self._evidence_remediation_calls,
            )
            if leftover_initial + reserved_remaining <= 0:
                raise BudgetExhaustedError(
                    EVIDENCE_REMEDIATION_BUDGET_REASON
                    if self.evidence_remediation_reserved > 0
                    else EVIDENCE_STAGE_CAP_REASON,
                    stage="evidence",
                )
            return
        raise ValueError(f"unknown evidence purpose: {resolved!r}")

    def record_llm_call(
        self,
        stage: str,
        *,
        purpose: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        elapsed_ms: int = 0,
        retry: bool = False,
    ) -> None:
        if stage == "evidence":
            resolved = purpose or EVIDENCE_PURPOSE_INITIAL
            if resolved == EVIDENCE_PURPOSE_REMEDIATION:
                self._evidence_remediation_calls += 1
            else:
                self._evidence_initial_calls += 1
        usage = self._stage_usage.setdefault(stage, StageBudgetUsage(stage=stage))
        usage.llm_calls += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.reasoning_tokens += reasoning_tokens
        usage.elapsed_ms += elapsed_ms
        if retry:
            usage.retries += 1
        self._total_llm_calls += 1
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._mark_stage_cap_if_reached(stage)
        self._check_fatal_exhaustion(stage)

    def _mark_stage_cap_if_reached(self, stage: str) -> None:
        usage = self._stage_usage.get(stage)
        if usage is None:
            return
        limit = self.stage_cap_limit(stage)
        if limit is not None and usage.llm_calls >= limit:
            usage.stage_cap_reached = True

    def _check_fatal_exhaustion(self, stage: str) -> None:
        """Mark only run-level fatal exhaustion; stage caps are non-fatal."""
        if self._total_llm_calls >= self.llm_max_calls_per_run:
            self._exhausted = True
            self._exhaustion_reason = "llm_max_calls_per_run"
            self._exhaustion_stage = stage
            return
        if (
            self.max_input_tokens_per_run is not None
            and self._total_input_tokens > self.max_input_tokens_per_run
        ):
            self._exhausted = True
            self._exhaustion_reason = "max_input_tokens_per_run"
            self._exhaustion_stage = stage
            return
        if (
            self.max_output_tokens_per_run is not None
            and self._total_output_tokens > self.max_output_tokens_per_run
        ):
            self._exhausted = True
            self._exhaustion_reason = "max_output_tokens_per_run"
            self._exhaustion_stage = stage

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def exhaustion_reason(self) -> str | None:
        return self._exhaustion_reason

    @property
    def exhaustion_stage(self) -> str | None:
        return self._exhaustion_stage

    def evidence_partition_snapshot(self) -> dict[str, Any]:
        return {
            "total_max": self.evidence_max_llm_calls,
            "initial_allowance": self.evidence_initial_allowance,
            "remediation_reserved": self.evidence_remediation_reserved,
            "initial_calls": self._evidence_initial_calls,
            "remediation_calls": self._evidence_remediation_calls,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "total_llm_calls": self._total_llm_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "exhausted": self._exhausted,
            "exhaustion_reason": self._exhaustion_reason,
            "exhaustion_stage": self._exhaustion_stage,
            "evidence_partition": self.evidence_partition_snapshot(),
            "stages": {
                name: usage.to_dict() for name, usage in self._stage_usage.items()
            },
        }
