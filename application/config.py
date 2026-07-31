from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.ports.project_repository import ProjectRepository
from application.services.project_service import ProjectService
from infrastructure.llm.llm_client import LLMClient

from registry.registry import Registry


@dataclass(frozen=True)
class ApplicationConfig:
    """
    Application-level configuration for composition.
    """

    llm_model: str = "gpt-5"
    llm_max_tokens: int = 4096
    projects_root: str = "agency/projects"
    persistence_backend: str = "file"
    database_url: str | None = None


@dataclass
class ApplicationOverrides:
    """
    Optional dependency overrides for tests and custom wiring.
    """

    llm_client: LLMClient | None = None
    project_repository: ProjectRepository | None = None
    project_service: ProjectService | None = None
    registry: Registry | None = None
    planner_agent: Any | None = None
