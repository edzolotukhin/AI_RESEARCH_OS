from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from application.composition_root import create_application_container
from application.config import ApplicationConfig
from application.container import ApplicationContainer

from api import API_VERSION, SERVICE_NAME
from api.errors import register_exception_handlers
from api.routers import artifacts, health, projects, workflow_runs


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
    app.include_router(workflow_runs.router)
    app.include_router(artifacts.router)

    return app
