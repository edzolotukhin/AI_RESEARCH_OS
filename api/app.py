from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from application.composition_root import create_application_container
from application.config import ApplicationConfig
from application.container import ApplicationContainer

from api import API_VERSION, SERVICE_NAME
from api.errors import register_exception_handlers
from api.routers import (
    artifacts,
    evidence,
    findings,
    health,
    projects,
    reports,
    research,
    reviews,
    sources,
    ui_research,
    workflow_runs,
)


def create_fastapi_app(
    *,
    container: ApplicationContainer | None = None,
    config: ApplicationConfig | None = None,
) -> FastAPI:
    """
    Build a FastAPI application wired through the Composition Root.

    When ``container`` is omitted, a new container is created from ``config``
    (or ``ApplicationConfig.from_env()``). Tests should pass an explicit
    in-memory container to avoid unexpected PostgreSQL connections.
    """
    app_container = container
    owns_container = app_container is None

    if app_container is None:
        app_container = create_application_container(
            config=config or ApplicationConfig.from_env(),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if owns_container:
            app_container.shutdown()

    app = FastAPI(
        title="AI Research OS API",
        description=(
            "HTTP boundary for the AI Research OS workflow runtime. "
            "POST /projects/{id}/research validates and plans synchronously, "
            "persists the run, returns 202 Accepted, and executes the workflow "
            "in a background worker. Live planning requires OPENAI_API_KEY when "
            "using the default OpenAI client."
        ),
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.state.container = app_container

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(research.router)
    app.include_router(ui_research.router)
    app.include_router(workflow_runs.router)
    app.include_router(artifacts.router)
    app.include_router(sources.router)
    app.include_router(evidence.router)
    app.include_router(findings.router)
    app.include_router(reports.router)
    app.include_router(reviews.router)

    ui_research.mount_ui_static(app)

    _configure_openapi_security(app)

    return app


def _configure_openapi_security(app: FastAPI) -> None:
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema.setdefault("components", {}).setdefault(
            "securitySchemes",
            {},
        )["ApiKeyBearer"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Service API key issued via bootstrap CLI.",
        }
        public_paths = {"/health", "/ready", "/openapi.json", "/docs", "/redoc", "/ui", "/static"}
        for path, methods in openapi_schema.get("paths", {}).items():
            if path in public_paths or path.startswith("/ui/"):
                continue
            for operation in methods.values():
                if isinstance(operation, dict):
                    operation.setdefault("security", [{"ApiKeyBearer": []}])
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
