from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JsonValidationResult:
    is_valid: bool
    data: Any | None = None
    error: str | None = None
    error_line: int | None = None
    error_column: int | None = None
    error_position: int | None = None


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
                error=exc.msg,
                error_line=exc.lineno,
                error_column=exc.colno,
                error_position=exc.pos,
            )

        return JsonValidationResult(
            is_valid=True,
            data=data,
        )
