from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.research.design_validator import validate_research_design
from domain.planning.research_design import ResearchDesign
from domain.project import Project

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
        validate_research_design(
            design,
            brief=project.research_brief,
        )
        return design
