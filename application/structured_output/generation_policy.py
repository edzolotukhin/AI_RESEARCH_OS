from __future__ import annotations

import os
from dataclasses import dataclass

from infrastructure.llm.generation_options import LLMGenerationOptions

REASONING_EFFORT_ORDER = ("minimal", "low", "medium", "high")
DEFAULT_PLANNER_REASONING_EFFORT = "minimal"
DEFAULT_PLANNER_MAX_OUTPUT_TOKENS = 8192
PLANNER_TOKEN_ESCALATION_STEP = 8192


@dataclass(frozen=True)
class StructuredGenerationPolicy:
    """
    Bounded generation settings for structured JSON stages.
    """

    reasoning_effort: str
    max_output_tokens: int
    escalation_reasoning_effort: str | None = None
    escalation_max_output_tokens: int | None = None

    def initial_options(self) -> LLMGenerationOptions:
        return LLMGenerationOptions(
            max_output_tokens=self.max_output_tokens,
            reasoning_effort=self.reasoning_effort,
        )

    def escalate(self, current: LLMGenerationOptions) -> LLMGenerationOptions:
        next_effort = self.escalation_reasoning_effort or current.reasoning_effort
        if current.reasoning_effort is not None and next_effort is not None:
            next_effort = _lower_reasoning_effort(current.reasoning_effort, next_effort)

        next_tokens = current.max_output_tokens or self.max_output_tokens
        if (
            self.escalation_max_output_tokens is not None
            and next_tokens < self.escalation_max_output_tokens
        ):
            next_tokens = self.escalation_max_output_tokens

        return LLMGenerationOptions(
            max_output_tokens=next_tokens,
            reasoning_effort=next_effort,
        )

    @classmethod
    def planner_from_env(cls) -> StructuredGenerationPolicy:
        effort = os.environ.get(
            "PLANNER_REASONING_EFFORT",
            DEFAULT_PLANNER_REASONING_EFFORT,
        ).strip().lower()
        max_tokens = int(
            os.environ.get(
                "PLANNER_MAX_OUTPUT_TOKENS",
                str(DEFAULT_PLANNER_MAX_OUTPUT_TOKENS),
            )
        )
        escalation_tokens = max(max_tokens, PLANNER_TOKEN_ESCALATION_STEP)

        return cls(
            reasoning_effort=effort,
            max_output_tokens=max_tokens,
            escalation_reasoning_effort="minimal",
            escalation_max_output_tokens=escalation_tokens,
        )


def _lower_reasoning_effort(current: str, target: str) -> str:
    normalized_current = current.strip().lower()
    normalized_target = target.strip().lower()

    try:
        current_index = REASONING_EFFORT_ORDER.index(normalized_current)
    except ValueError:
        current_index = len(REASONING_EFFORT_ORDER)

    try:
        target_index = REASONING_EFFORT_ORDER.index(normalized_target)
    except ValueError:
        target_index = len(REASONING_EFFORT_ORDER)

    return REASONING_EFFORT_ORDER[min(current_index, target_index)]
