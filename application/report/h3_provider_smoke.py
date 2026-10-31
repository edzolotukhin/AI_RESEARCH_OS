"""Explicitly opt-in, non-persistent H3 provider contract smoke harness."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from application.report.h3_claim_generation import _decode_response


class H3ProviderSmokeDisabled(RuntimeError):
    pass


def validate_h3_provider_smoke(
    *, provider: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Call an explicitly supplied production adapter once and discard output.

    This function has no repository, workflow, or persistence dependency. It is
    intentionally disabled unless the caller opts in through an environment
    variable so normal tests and deployment cannot invoke a real provider.
    """
    if os.getenv("AI_RESEARCH_ENABLE_H3_PROVIDER_SMOKE") != "1":
        raise H3ProviderSmokeDisabled("h3_provider_smoke_not_enabled")
    response = provider(dict(request))
    decoded = _decode_response(response)
    return {"validated_claim_ids": sorted(decoded), "provider_calls": 1}
