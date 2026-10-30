from __future__ import annotations

import json
from typing import Any, Mapping

from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt


class LlmH3EditorialProvider:
    def __init__(self, client) -> None:
        self._client = client

    def compose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._client.generate(Prompt(
            system=(
                "Return only a JSON H3 typed editorial document. Use only the supplied "
                "opaque claim and authority references; never invent factual values."
            ),
            user=json.dumps(dict(request), ensure_ascii=False, sort_keys=True),
        ))
        result = JsonValidator().validate(response.content or "")
        if not result.is_valid or not isinstance(result.data, Mapping):
            raise ValueError("h3_editorial_provider_invalid")
        return result.data
