from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from domain.planning.research_design import ResearchDesign
from domain.planning.research_plan import ResearchPlan
from domain.project import Project
from domain.workflow_template import WorkflowTemplate


class PlannerDesignService(Protocol):
    """Application contract for creating a semantic research design."""

    def create_design(
        self,
        project: Project,
        design_data: Mapping[str, Any],
    ) -> ResearchDesign:
        ...


class ResearchDesignWorkflowMapperProtocol(Protocol):
    """Maps semantic ResearchDesign to WorkflowTemplate."""

    def from_research_design(
        self,
        design: ResearchDesign,
        project: Project,
    ) -> WorkflowTemplate:
        ...


class PlannerService(Protocol):
    """
    Legacy ResearchPlan contract (DR-01).

    Deprecated: production uses PlannerDesignService.
    Removal condition: delete when ResearchPlan unit tests migrate or retire.
    """

    def create_plan(
        self,
        project: Project,
        plan_data: Mapping[str, Any],
    ) -> ResearchPlan:
        ...


class WorkflowTemplateMapper(Protocol):
    """
    Legacy ResearchPlan workflow mapper protocol.

    Deprecated: production uses ResearchDesignWorkflowMapperProtocol.
    """

    def from_research_plan(
        self,
        plan: ResearchPlan,
        project: Project,
    ) -> WorkflowTemplate:
        ...
