"""LLM test doubles that emit brief-aligned ResearchDesign JSON."""

from __future__ import annotations

from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse

from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
)


def create_brief_aligned_llm_mock() -> Mock:
    mock = Mock()

    def _generate(prompt):
        return LLMResponse(content=build_deterministic_design_response(prompt))

    mock.generate.side_effect = _generate
    return mock
