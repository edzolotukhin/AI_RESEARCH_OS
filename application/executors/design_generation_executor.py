from __future__ import annotations

from application.contracts.base_executor import BaseExecutor
from application.exceptions.structured_output_error import StructuredOutputError
from application.persistence.exceptions import ConcurrentModificationError
from application.planner.project_planning_profile import ProjectPlanningProfile
from application.planner.project_planning_profile import PROJECT_PLANNING_PROFILE_KEY
from application.services.project_planning_service import ProjectPlanningService
from domain.research_method import canonicalize_research_methods
from domain.common.exceptions import ValidationError


DESIGN_GENERATION_DIAGNOSTIC_KEY = "design_generation"


def _failure_category(error: BaseException) -> str:
    if isinstance(error, (StructuredOutputError, ValidationError, ValueError)):
        return "generated_design_validation_failure"
    if isinstance(error, ConcurrentModificationError):
        return "other_design_generation_failure"
    return "provider_model_execution_failure"


class DesignGenerationExecutor(BaseExecutor):
    """Runs project-level planning inside the durable worker boundary."""

    def __init__(self, *, planner_agent, project_service) -> None:
        self._planner = planner_agent
        self._projects = project_service

    def run(self, context):
        project = context.project
        methods = canonicalize_research_methods(project.selected_methods or ("DESK",))
        expected_fingerprint = context.workflow_template.id.rsplit(":", 1)[-1]
        diagnostic = {
            "version": 1,
            "status": "running",
            "category": None,
            "project_id": project.id,
            "workflow_run_id": context.workflow_run.id,
            "input_fingerprint": expected_fingerprint,
        }
        context.write_shared(DESIGN_GENERATION_DIAGNOSTIC_KEY, diagnostic)
        try:
            current_fingerprint = ProjectPlanningService.input_fingerprint(
                project.research_brief, methods,
            )
            if current_fingerprint != expected_fingerprint:
                raise ValueError("Бриф змінився; сформуйте актуальний дизайн")
            if (
                project.current_research_design is not None
                and project.research_design_input_fingerprint == expected_fingerprint
                and ProjectPlanningService._design_is_resolved(
                    project.current_research_design
                )
            ):
                context.write_shared(DESIGN_GENERATION_DIAGNOSTIC_KEY, {
                    **diagnostic,
                    "status": "completed",
                    "design_id": project.current_research_design.id,
                })
                return context
            context.execution_metadata[PROJECT_PLANNING_PROFILE_KEY] = (
                ProjectPlanningProfile(
                    methods=methods,
                    language=project.research_brief.language,
                ).to_metadata()
            )
            planned = self._planner.run(context)
            template = planned.workflow_template
            if template is None or template.research_design_snapshot is None:
                raise ValueError("Планувальник не сформував дизайн дослідження")
            fingerprint = current_fingerprint
            project.current_research_design = template.research_design_snapshot
            project.research_design_status = "DRAFT"
            project.research_design_input_fingerprint = fingerprint
            project.research_design_approved_by = None
            project.research_design_approved_at = None
            from domain.value_objects.project_status import ProjectStatus
            project.status = ProjectStatus.RESEARCH_DESIGN
            self._projects.save_project(project)
        except Exception as error:
            context.write_shared(DESIGN_GENERATION_DIAGNOSTIC_KEY, {
                **diagnostic,
                "status": "failed",
                "category": _failure_category(error),
            })
            raise
        context.write_shared(DESIGN_GENERATION_DIAGNOSTIC_KEY, {
            "version": 1, "project_id": project.id,
            "workflow_run_id": context.workflow_run.id,
            "input_fingerprint": fingerprint, "status": "completed",
            "category": None,
            "design_id": template.research_design_snapshot.id,
        })
        return planned
