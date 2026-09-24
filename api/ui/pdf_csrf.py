"""Action-bound UI CSRF token for PDF generation forms."""

from __future__ import annotations

import hashlib
import hmac
import os


def _key(container) -> bytes:
    value = ((os.environ.get("UI_INTERNAL_API_KEY") or "").strip()
             or (os.environ.get("AI_RESEARCH_OS_API_KEY") or "").strip()
             or getattr(container, "_test_api_key_plaintext", None))
    if not value:
        raise RuntimeError("UI credentials unavailable")
    return value.encode("utf-8")


def token(container, owner_id: str, project_id: str, method: str, source_id: str,
          action: str = "pdf") -> str:
    if action not in {"pdf", "pptx"}:
        raise ValueError("unsupported CSRF action")
    message = "\x1f".join((f"{action}-generation-v1", owner_id, project_id, method, source_id))
    return hmac.new(_key(container), message.encode("utf-8"), hashlib.sha256).hexdigest()


def valid(container, owner_id: str, project_id: str, method: str,
          source_id: str, candidate: str, action: str = "pdf") -> bool:
    return hmac.compare_digest(token(container, owner_id, project_id, method, source_id, action),
                               candidate)
