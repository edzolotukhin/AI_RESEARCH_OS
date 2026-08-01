from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from application.execution.exceptions import ClaimConflictError
from application.persistence.exceptions import (
    CheckpointPersistenceError,
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.runtime.task_result_codec import NonSerializableTaskResultError

from api.schemas.common import ErrorDetail, ErrorResponse


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or {},
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ClaimConflictError)
    async def handle_claim_conflict(
        _: Request,
        exc: ClaimConflictError,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="run_claim_conflict",
            message=str(exc),
        )

    @app.exception_handler(EntityNotFoundError)
    async def handle_not_found(_: Request, exc: EntityNotFoundError) -> JSONResponse:
        return _error_response(
            status_code=404,
            code="entity_not_found",
            message=str(exc),
        )

    @app.exception_handler(DuplicateEntityError)
    async def handle_duplicate(_: Request, exc: DuplicateEntityError) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="duplicate_entity",
            message=str(exc),
        )

    @app.exception_handler(ConcurrentModificationError)
    async def handle_concurrency(
        _: Request,
        exc: ConcurrentModificationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="concurrent_modification",
            message=str(exc),
        )

    @app.exception_handler(NonSerializableTaskResultError)
    async def handle_non_serializable(
        _: Request,
        exc: NonSerializableTaskResultError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="non_serializable_task_result",
            message=str(exc),
        )

    @app.exception_handler(CheckpointPersistenceError)
    async def handle_checkpoint_failure(
        _: Request,
        exc: CheckpointPersistenceError,
    ) -> JSONResponse:
        return _error_response(
            status_code=500,
            code="checkpoint_persistence_failed",
            message="Workflow checkpoint could not be persisted.",
            details={"reason": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="validation_error",
            message=str(exc),
        )

    @app.exception_handler(RuntimeError)
    async def handle_runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
        message = str(exc)
        if "PAUSED WorkflowRun resume" in message:
            return _error_response(
                status_code=409,
                code="paused_resume_not_supported",
                message=message,
            )
        if "Durable workflow execution is not enabled" in message:
            return _error_response(
                status_code=409,
                code="durable_execution_unavailable",
                message=message,
            )
        if "Durable background workflow execution is not enabled" in message:
            return _error_response(
                status_code=409,
                code="durable_execution_unavailable",
                message=message,
            )
        return _error_response(
            status_code=500,
            code="internal_error",
            message="An internal error occurred.",
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="request_validation_error",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            status_code=500,
            code="internal_error",
            message="An internal error occurred.",
        )
