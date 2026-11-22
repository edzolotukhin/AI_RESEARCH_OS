from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.research.design_validator import validate_research_design
from domain.planning.research_design import ResearchDesign
from domain.project import Project
from application.research.subject_resolution import resolve_subject_proposal
from application.services.project_planning_service import ProjectPlanningService

from .contracts import PlannerDesignService


class PlannerDesignServiceImpl(PlannerDesignService):
    """Builds a validated ResearchDesign from structured planner output."""

    def __init__(
        self,
        response_parser: ResearchDesignParser,
        design_factory: ResearchDesignFactory,
    ) -> None:
        self._response_parser = response_parser
        self._design_factory = design_factory

    def create_design(
        self,
        project: Project,
        design_data: Mapping[str, Any],
    ) -> ResearchDesign:
        dto = self._response_parser.parse(design_data)
        design = self._design_factory.create(dto)
        subject = resolve_subject_proposal(
            project.research_brief,
            dto.research_subject_proposal,
            design=design,
        ) if project.research_brief is not None else None
        design = replace(design, research_subject=subject)
        brief = project.research_brief
        if (
            brief is not None
            and brief.objective_registry is not None
            and design.objective_reference_contract == "objective_ids_v1"
        ):
            design = replace(
                design,
                brief_fingerprint=ProjectPlanningService.input_fingerprint(
                    brief, tuple(project.selected_methods or ())
                ),
                objective_registry_identity=brief.objective_registry_identity,
            )
        expected_fingerprint = None
        if brief is not None:
            expected_fingerprint = ProjectPlanningService.input_fingerprint(
                brief, tuple(project.selected_methods or ())
            )
        validate_research_design(
            design,
            brief=project.research_brief,
            expected_brief_fingerprint=expected_fingerprint,
        )
        return design
