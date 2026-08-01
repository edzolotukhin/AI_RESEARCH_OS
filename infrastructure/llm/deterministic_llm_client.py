from __future__ import annotations

from pathlib import Path

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient

_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "deterministic_planner_response.json"
)


class DeterministicLLMClient(LLMClient):
    """
    Offline LLM client for local Compose smoke and development.

    Returns a fixed planner JSON payload without calling a live model.
    """

    def __init__(self, *, fixture_path: Path | None = None) -> None:
        path = fixture_path or _FIXTURE_PATH
        self._content = path.read_text(encoding="utf-8").strip()

    def generate(self, prompt: Prompt) -> LLMResponse:
        return LLMResponse(content=self._content)
