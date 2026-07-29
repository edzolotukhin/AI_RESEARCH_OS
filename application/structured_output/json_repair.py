from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JsonRepairResult:
    text: str
    has_unclosed_string: bool
    has_unclosed_container: bool


class JsonRepair:
    """
    Applies strictly safe, deterministic repairs to malformed JSON text.
    """

    _TRAILING_COMMA = re.compile(r",(\s*[}\]])")

    def try_repair(
        self,
        text: str,
    ) -> JsonRepairResult:
        repaired = self._TRAILING_COMMA.sub(r"\1", text.strip())

        return JsonRepairResult(
            text=repaired,
            has_unclosed_string=self._has_unclosed_string(repaired),
            has_unclosed_container=self._has_unclosed_container(repaired),
        )

    def _has_unclosed_string(
        self,
        text: str,
    ) -> bool:
        in_string = False
        escape = False

        for char in text:
            if in_string:
                if escape:
                    escape = False
                    continue

                if char == "\\":
                    escape = True
                    continue

                if char == '"':
                    in_string = False

                continue

            if char == '"':
                in_string = True

        return in_string

    def _has_unclosed_container(
        self,
        text: str,
    ) -> bool:
        stack: list[str] = []
        in_string = False
        escape = False

        for char in text:
            if in_string:
                if escape:
                    escape = False
                    continue

                if char == "\\":
                    escape = True
                    continue

                if char == '"':
                    in_string = False

                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                stack.append("}")
                continue

            if char == "[":
                stack.append("]")
                continue

            if char in "}]" and stack and stack[-1] == char:
                stack.pop()

        return bool(stack)
