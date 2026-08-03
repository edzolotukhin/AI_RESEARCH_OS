from __future__ import annotations

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient

from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
)


class DeterministicLLMClient(LLMClient):
    """
    Offline LLM client for local Compose smoke and development.

    Returns brief-aligned ResearchDesign JSON without calling a live model.
    """

    def generate(self, prompt: Prompt, *, options=None) -> LLMResponse:
        return LLMResponse(
            content=build_deterministic_design_response(prompt),
        )
