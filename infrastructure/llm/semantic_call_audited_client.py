from __future__ import annotations

from hashlib import sha256

from application.quantitative.execution_diagnostics import get_semantic_call_recorder, semantic_stage
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient


class SemanticCallAuditedClient(LLMClient):
    """Audit wrapper for injected/test quantitative provider clients."""

    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate

    def generate(self, prompt: Prompt, *, options: LLMGenerationOptions | None = None):
        recorder = get_semantic_call_recorder(); stage = semantic_stage()
        if recorder is None or stage is None:
            return self._delegate.generate(prompt, options=options)
        input_fingerprint = sha256((prompt.system + "\n" + prompt.user).encode()).hexdigest()
        call_id = recorder.planned(stage=stage, provider=type(self._delegate).__name__, model="injected", input_fingerprint=input_fingerprint)
        recorder.dispatched(call_id)
        try:
            response = self._delegate.generate(prompt, options=options)
        except Exception as exc:
            recorder.failed(call_id, exc, after_dispatch=True)
            raise
        recorder.returned(call_id, sha256((response.content or "").encode()).hexdigest())
        return response
