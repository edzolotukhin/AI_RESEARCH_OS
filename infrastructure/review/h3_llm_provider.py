from __future__ import annotations

import json
from typing import Any, Mapping

from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt


class LlmH3ReviewProvider:
    def __init__(self, client) -> None:
        self._client = client

    def review(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self._client.generate(Prompt(
            system=(
                "Review only the supplied H3 typed presentation for editorial quality. "
                "Return JSON with decision APPROVE, REVISE, or REJECT and issues."
            ),
            user=json.dumps(dict(request), ensure_ascii=False, sort_keys=True),
        ))
        result = JsonValidator().validate(response.content or "")
        if not result.is_valid or not isinstance(result.data, Mapping):
            raise ValueError("h3_review_provider_invalid")
        return result.data
