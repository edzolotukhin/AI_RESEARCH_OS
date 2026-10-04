"""Provider adapters for closed-world QUA-02 structured analysis proposals."""
from __future__ import annotations

import json
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from application.structured_output.json_validator import JsonValidator


class LLMQualitativeAnalysisProvider:
    def __init__(self, llm_client): self.llm_client=llm_client

    def propose(self, request):
        prompt=Prompt(system=("Return one JSON object only. Work exclusively from supplied canonical transcript/coding "
            "material. Every application and theme evidence reference must use supplied identifiers. Do not use web, "
            "Desk, Quant, ARK or world knowledge."),user=json.dumps(request,ensure_ascii=False,sort_keys=True))
        response=self.llm_client.generate(prompt,options=LLMGenerationOptions(max_output_tokens=4000))
        result=JsonValidator().validate(response.content)
        if not result.is_valid or not isinstance(result.data,dict): raise ValueError("Invalid qualitative provider output")
        return result.data


class DeterministicQualitativeAnalysisProvider:
    def __init__(self, responses): self.responses=dict(responses); self.calls=[]
    def propose(self, request):
        self.calls.append(request)
        value=self.responses.get(request["batch_key"])
        if value is None: raise ValueError("No deterministic qualitative response")
        return value
