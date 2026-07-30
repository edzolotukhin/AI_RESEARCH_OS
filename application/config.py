from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infrastructure.llm.llm_client import LLMClient

from infrastructure.project_repository import ProjectRepository

from registry.registry import Registry


@dataclass(frozen=True)
class ApplicationConfig:
    """
    Application-level configuration for composition.
    """

    llm_model: str = "gpt-5"
    llm_max_tokens: int = 4096
    projects_root: str = "agency/projects"
    workflow_run_id: str = "run-001"


@dataclass
class ApplicationOverrides:
    """
    Optional dependency overrides for tests and custom wiring.
    """

    llm_client: LLMClient | None = None
    project_repository: ProjectRepository | None = None
    registry: Registry | None = None
    planner_agent: Any | None = None
