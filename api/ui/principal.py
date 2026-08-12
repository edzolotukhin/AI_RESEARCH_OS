"""Server-side principal resolution for internal Research UI."""

from __future__ import annotations

import os

from application.container import ApplicationContainer
from application.persistence.exceptions import AuthenticationRequiredError
from application.security.principal import AuthenticatedPrincipal


def resolve_ui_principal(container: ApplicationContainer) -> AuthenticatedPrincipal:
    """Resolve trusted internal credentials without exposing them to the browser."""
    if container.authentication_service is None:
        raise RuntimeError("Authentication is not configured for this deployment.")

    api_key = (
        (os.environ.get("UI_INTERNAL_API_KEY") or "").strip()
        or (os.environ.get("AI_RESEARCH_OS_API_KEY") or "").strip()
        or getattr(container, "_test_api_key_plaintext", None)
    )
    if not api_key:
        raise AuthenticationRequiredError(
            "UI internal credentials are not configured.",
        )
    return container.authentication_service.authenticate_api_key(api_key)
