from __future__ import annotations

import re


class ResponseCleaner:
    """
    Normalizes raw LLM text before JSON extraction.

    Removes markdown fences and common wrapper formatting without
    interpreting business meaning.
    """

    _FENCED_BLOCK = re.compile(
        r"```(?:json|JSON)?\s*(.*?)\s*```",
        re.DOTALL,
    )
    _OPENING_FENCE = re.compile(r"^```(?:json|JSON)?\s*", re.MULTILINE)
    _CLOSING_FENCE = re.compile(r"\s*```\s*$", re.MULTILINE)

    def clean(
        self,
        raw_text: str,
    ) -> str:
        text = raw_text.strip()

        if not text:
            return text

        fenced_match = self._FENCED_BLOCK.search(text)
        if fenced_match is not None:
            return fenced_match.group(1).strip()

        text = self._OPENING_FENCE.sub("", text)
        text = self._CLOSING_FENCE.sub("", text)

        return text.strip()
