from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from application.persistence.exceptions import AuthenticationRequiredError
from application.security.principal import AuthenticatedPrincipal
from application.services.authorization_service import AuthorizationService

from api.dependencies import ContainerDep, get_container

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKeyBearer",
    description="Service API key issued via bootstrap CLI.",
)


def get_current_principal(
    container: ContainerDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedPrincipal:
    if container.authentication_service is None:
        raise RuntimeError("Authentication is not configured for this deployment.")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationRequiredError("Authentication credentials were not provided.")

    return container.authentication_service.authenticate_api_key(credentials.credentials)


def get_authorization_service(container: ContainerDep) -> AuthorizationService:
    if container.authorization_service is None:
        raise RuntimeError("Authorization is not configured for this deployment.")
    return container.authorization_service


PrincipalDep = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]
AuthorizationDep = Annotated[
    AuthorizationService,
    Depends(get_authorization_service),
]
