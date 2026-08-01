from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Authentication-neutral caller identity for application authorization."""

    principal_id: str
    name: str
    authentication_type: str = "api_key"
    api_key_id: str | None = None
    key_prefix: str | None = None
