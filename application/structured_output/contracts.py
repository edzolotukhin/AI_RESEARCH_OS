from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class StructuredPayloadContract(Protocol):
    """
    Validates whether a parsed JSON object matches an expected payload shape.
    """

    def accepts(
        self,
        payload: Mapping[str, Any],
    ) -> bool:
        ...
