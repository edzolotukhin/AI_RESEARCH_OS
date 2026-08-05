from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.execution.execution_budget import ExecutionBudget, StageBudgetUsage


@dataclass
class RunUsageSummary:
    workflow_run_id: str
    stages: dict[str, StageBudgetUsage] = field(default_factory=dict)
    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_elapsed_ms: int = 0
    budget_exhausted: bool = False
    exhaustion_reason: str | None = None
    estimated_cost_usd: float | None = None

    def merge_budget(self, budget: ExecutionBudget) -> None:
        summary = budget.summary()
        self.total_llm_calls = summary["total_llm_calls"]
        self.total_input_tokens = summary["total_input_tokens"]
        self.total_output_tokens = summary["total_output_tokens"]
        self.budget_exhausted = summary["exhausted"]
        self.exhaustion_reason = summary["exhaustion_reason"]
        for name, data in summary["stages"].items():
            self.stages[name] = StageBudgetUsage(
                stage=name,
                llm_calls=data["llm_calls"],
                retries=data["retries"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                reasoning_tokens=data["reasoning_tokens"],
                elapsed_ms=data["elapsed_ms"],
            )
        self.total_reasoning_tokens = sum(
            s.reasoning_tokens for s in self.stages.values()
        )
        self.total_elapsed_ms = sum(s.elapsed_ms for s in self.stages.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "total_llm_calls": self.total_llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
            "total_elapsed_ms": self.total_elapsed_ms,
            "budget_exhausted": self.budget_exhausted,
            "exhaustion_reason": self.exhaustion_reason,
            "estimated_cost_usd": self.estimated_cost_usd,
            "stages": {name: s.to_dict() for name, s in self.stages.items()},
        }
