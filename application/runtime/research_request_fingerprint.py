from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_research_request_fingerprint(
    *,
    project_id: str,
    brief: dict[str, Any],
) -> str:
    """
    Deterministic fingerprint of semantic research submission input.

    Excludes timestamps, trace IDs, callback metadata, and transport headers.
    """
    payload = {
        "project_id": project_id,
        "brief": _canonicalize(brief),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value
