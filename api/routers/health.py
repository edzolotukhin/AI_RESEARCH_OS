from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api import API_VERSION, SERVICE_NAME
from api.dependencies import ContainerDep
from api.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application liveness probe",
    operation_id="getHealth",
)
def get_health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=API_VERSION,
        persistence_backend=container.config.persistence_backend,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Application readiness probe",
    operation_id="getReadiness",
    responses={503: {"description": "Required dependencies are unavailable."}},
)
def get_readiness(container: ContainerDep) -> ReadinessResponse | JSONResponse:
    ready, reason = container.check_readiness()
    response = ReadinessResponse(
        status="ready" if ready else "not_ready",
        service=SERVICE_NAME,
        persistence_backend=container.config.persistence_backend,
        reason=None if ready else reason,
    )
    if not ready:
        return JSONResponse(
            status_code=503,
            content=response.model_dump(),
        )
    return response
