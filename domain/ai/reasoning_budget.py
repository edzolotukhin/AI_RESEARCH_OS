from __future__ import annotations

from domain.ai.llm_response import LLMResponse

REASONING_TOKEN_SHARE_THRESHOLD = 0.5
NEAR_MAX_OUTPUT_TOKEN_RATIO = 0.95
SMALL_VISIBLE_OUTPUT_CHAR_LIMIT = 2000


def is_reasoning_budget_exhaustion(response: LLMResponse) -> bool:
    """
    Detect max-token truncation driven primarily by reasoning-token consumption.
    """
    if not response.was_truncated:
        return False

    reasoning_tokens = response.reasoning_tokens
    output_tokens = response.output_tokens

    if reasoning_tokens is None or output_tokens is None or output_tokens <= 0:
        return False

    if reasoning_tokens <= 0:
        return False

    reasoning_share = reasoning_tokens / output_tokens
    if reasoning_share >= REASONING_TOKEN_SHARE_THRESHOLD:
        return True

    visible_length = len(response.content or "")
    max_output_tokens = response.max_output_tokens

    if (
        max_output_tokens
        and output_tokens >= max_output_tokens * NEAR_MAX_OUTPUT_TOKEN_RATIO
        and visible_length <= SMALL_VISIBLE_OUTPUT_CHAR_LIMIT
    ):
        return True

    return False
