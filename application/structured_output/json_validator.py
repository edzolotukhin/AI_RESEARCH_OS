from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JsonValidationResult:
    is_valid: bool
    data: Any | None = None
    error: str | None = None


class JsonValidator:
    """
    Performs syntax-only JSON validation via json.loads().
    """

    def validate(
        self,
        text: str,
    ) -> JsonValidationResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return JsonValidationResult(
                is_valid=False,
                error=str(exc),
            )

        return JsonValidationResult(
            is_valid=True,
            data=data,
        )
