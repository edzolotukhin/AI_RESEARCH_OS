"""Server-side principal resolution for internal Research UI."""

from __future__ import annotations

from application.container import ApplicationContainer
from application.persistence.exceptions import AuthenticationRequiredError
from application.security.principal import AuthenticatedPrincipal
from api.ui.session import current_ui_user


def resolve_ui_principal(container: ApplicationContainer) -> AuthenticatedPrincipal:
    """Resolve trusted internal credentials without exposing them to the browser."""
    if container.authentication_service is None:
        raise RuntimeError("Authentication is not configured for this deployment.")

    user = current_ui_user.get()
    if user is None and getattr(container, "_test_api_key_plaintext", None):
        return container.authentication_service.authenticate_api_key(
            container._test_api_key_plaintext
        )
    if user is None:
        raise AuthenticationRequiredError("Your session has expired. Please sign in again.")
    if isinstance(user, AuthenticatedPrincipal):
        return user
    return AuthenticatedPrincipal(user.id, user.display_name, "browser_session")
