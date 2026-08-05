from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageBudgetUsage:
    stage: str
    llm_calls: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "llm_calls": self.llm_calls,
            "retries": self.retries,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ExecutionBudget:
    evidence_max_items_per_run: int = 500
    evidence_max_items_per_source: int = 50
    analysis_max_findings: int = 100
    analysis_max_insights: int = 30
    report_max_sections: int = 12
    report_max_llm_calls: int = 20
    review_max_llm_calls: int = 7
    llm_max_calls_per_run: int = 100
    max_input_tokens_per_run: int | None = None
    max_output_tokens_per_run: int | None = None

    _stage_usage: dict[str, StageBudgetUsage] = field(default_factory=dict, repr=False)
    _total_llm_calls: int = 0
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    _exhausted: bool = False
    _exhaustion_reason: str | None = None

    def record_llm_call(
        self,
        stage: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        elapsed_ms: int = 0,
        retry: bool = False,
    ) -> None:
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
        self._check_exhaustion(stage)

    def _check_exhaustion(self, stage: str) -> None:
        if self._total_llm_calls > self.llm_max_calls_per_run:
            self._exhausted = True
            self._exhaustion_reason = "llm_max_calls_per_run"
            return
        stage_usage = self._stage_usage.get(stage)
        if stage_usage is None:
            return
        if stage == "report" and stage_usage.llm_calls > self.report_max_llm_calls:
            self._exhausted = True
            self._exhaustion_reason = "report_max_llm_calls"
        if stage == "review" and stage_usage.llm_calls > self.review_max_llm_calls:
            self._exhausted = True
            self._exhaustion_reason = "review_max_llm_calls"
        if (
            self.max_input_tokens_per_run is not None
            and self._total_input_tokens > self.max_input_tokens_per_run
        ):
            self._exhausted = True
            self._exhaustion_reason = "max_input_tokens_per_run"
        if (
            self.max_output_tokens_per_run is not None
            and self._total_output_tokens > self.max_output_tokens_per_run
        ):
            self._exhausted = True
            self._exhaustion_reason = "max_output_tokens_per_run"

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def exhaustion_reason(self) -> str | None:
        return self._exhaustion_reason

    def summary(self) -> dict[str, Any]:
        return {
            "total_llm_calls": self._total_llm_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "exhausted": self._exhausted,
            "exhaustion_reason": self._exhaustion_reason,
            "stages": {
                name: usage.to_dict() for name, usage in self._stage_usage.items()
            },
        }
