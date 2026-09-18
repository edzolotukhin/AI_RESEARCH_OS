from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.workflow import build_quantitative_workflow_template
from application.planner.project_planning_profile import (
    PROJECT_PLANNING_PROFILE_VERSION,
    PROJECT_PLANNING_PROFILE_KEY,
    ProjectPlanningProfile,
)
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.research_method import (
    DESK,
    QUANTITATIVE,
    SUPPORTED_RESEARCH_METHODS,
    canonicalize_research_methods,
)
from domain.value_objects.project_status import ProjectStatus
from domain.workflow_run import WorkflowRun
from runtime.workflow_context import WorkflowContext


class ProjectPlanningError(ValueError):
    pass


class ProjectPlanningService:
    """Owns PF-02 project intent, design gate, and method activation."""

    def __init__(self, *, project_service, workflow_service, planner_agent,
                 workflow_mapper, agency, quantitative_ui_service) -> None:
        self.projects = project_service
        self.workflows = workflow_service
        self.planner = planner_agent
        self.workflow_mapper = workflow_mapper
        self.agency = agency
        self.quantitative = quantitative_ui_service

    def explicit_or_inferred_methods(self, project: Project) -> tuple[str, ...]:
        if project.selected_methods is not None:
            return canonicalize_research_methods(project.selected_methods, allow_empty=True)
        found: list[str] = []
        quant_template = build_quantitative_workflow_template().id
        for run in self.workflows.list_workflow_runs_for_project(project.id):
            quantitative = bool(
                self.quantitative
                and self.quantitative.state.list_for_run(
                    run.id,
                    project_id=project.id,
                    expected_type=self._study_type(),
                )
            )
            if quantitative and QUANTITATIVE not in found:
                found.append(QUANTITATIVE)
            elif not quantitative and run.workflow_template_id != quant_template and DESK not in found:
                found.append(DESK)
        return canonicalize_research_methods(found, allow_empty=True)

    def available_methods(self, project: Project) -> tuple[str, ...]:
        selected = set(self.explicit_or_inferred_methods(project))
        return tuple(item for item in SUPPORTED_RESEARCH_METHODS if item not in selected)

    def add_method(self, project: Project, method: str) -> Project:
        selected = self.explicit_or_inferred_methods(project)
        value = canonicalize_research_methods((method,))[0]
        if value in selected:
            return project
        project.selected_methods = canonicalize_research_methods((*selected, value))
        self._invalidate_design(project)
        self.projects.save_project(project)
        return project

    def remove_method(self, project: Project, method: str) -> Project:
        value = canonicalize_research_methods((method,))[0]
        selected = self.explicit_or_inferred_methods(project)
        if value not in selected:
            return project
        if self._is_activated(project.id, value):
            raise ProjectPlanningError("Активований метод не можна видалити")
        remaining = tuple(item for item in selected if item != value)
        if project.selected_methods is not None and not remaining:
            raise ProjectPlanningError("У проєкті має залишитися щонайменше один метод")
        project.selected_methods = canonicalize_research_methods(remaining, allow_empty=True)
        self._invalidate_design(project)
        self.projects.save_project(project)
        return project

    def save_brief(self, project: Project, brief: ResearchBrief) -> Project:
        if self._has_any_activation(project.id) and project.research_brief != brief:
            raise ProjectPlanningError("Бриф не можна змінити після активації методу")
        if project.research_brief == brief:
            return project
        project.research_brief = brief
        self._invalidate_design(project)
        self.projects.save_project(project)
        return project

    def generate_design(self, project: Project):
        methods = self.explicit_or_inferred_methods(project)
        if not methods:
            raise ProjectPlanningError("Оберіть щонайменше один метод дослідження")
        if project.research_brief is None:
            raise ProjectPlanningError("Спочатку збережіть дослідницький бриф")
        fingerprint = self.input_fingerprint(project.research_brief, methods)
        if (
            project.current_research_design is not None
            and project.research_design_input_fingerprint == fingerprint
        ):
            return project.current_research_design
        if self._has_any_activation(project.id) and all(
            self._is_activated(project.id, method) for method in methods
        ):
            raise ProjectPlanningError("Дизайн не можна переформувати після активації методу")
        context = WorkflowContext(
            project=project,
            workflow_run=WorkflowRun(id="planning"),
        )
        context.execution_metadata[PROJECT_PLANNING_PROFILE_KEY] = (
            ProjectPlanningProfile(
                methods=methods,
                language=project.research_brief.language,
            ).to_metadata()
        )
        planned = self.planner.run(context)
        template = planned.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ProjectPlanningError("Планувальник не сформував дизайн дослідження")
        project.current_research_design = template.research_design_snapshot
        project.research_design_status = "DRAFT"
        project.research_design_input_fingerprint = fingerprint
        project.research_design_approved_by = None
        project.research_design_approved_at = None
        project.status = ProjectStatus.RESEARCH_DESIGN
        self.projects.save_project(project)
        return project.current_research_design

    def approve_design(self, project: Project, *, actor_id: str,
                       expected_design_id: str) -> Project:
        design = project.current_research_design
        if design is None or design.id != expected_design_id:
            raise ProjectPlanningError("Дизайн змінився; оновіть сторінку")
        expected = self.input_fingerprint(
            project.research_brief,
            self.explicit_or_inferred_methods(project),
        )
        if project.research_design_input_fingerprint != expected:
            raise ProjectPlanningError("Дизайн потребує оновлення")
        if project.research_design_status == "APPROVED":
            return project
        project.research_design_status = "APPROVED"
        project.research_design_approved_by = actor_id
        project.research_design_approved_at = datetime.now(UTC).isoformat()
        project.status = ProjectStatus.APPROVED
        self.projects.save_project(project)
        return project

    def activate_desk(self, project: Project):
        self._require_activation(project, DESK)
        existing = self._desk_run(project.id)
        if existing is not None:
            return existing
        template = self.workflow_mapper.from_research_design(
            project.current_research_design,
            project,
        )
        run_id = str(uuid5(NAMESPACE_URL, f"pf02-desk:{project.id}"))
        return self.agency.start_research_from_template(
            project, template, run_id=run_id,
        ).workflow_run

    def activate_quantitative(self, project: Project, *, owner_id: str):
        self._require_activation(project, QUANTITATIVE)
        return self.quantitative.create_quantitative_study_for_project(
            project_id=project.id,
            owner_id=owner_id,
            title=f"{project.name} — кількісне дослідження",
            description="Кількісне дослідження в межах проєкту",
            submission_key="pf02-project-activation",
        )

    def design_is_current(self, project: Project) -> bool:
        if project.current_research_design is None or project.research_brief is None:
            return False
        return project.research_design_input_fingerprint == self.input_fingerprint(
            project.research_brief,
            self.explicit_or_inferred_methods(project),
        )

    @staticmethod
    def input_fingerprint(brief, methods: tuple[str, ...]) -> str:
        if brief is None:
            return ""
        payload = {
            "brief": brief.to_fingerprint_dict(),
            "selected_methods": list(methods),
            "planning_profile_version": PROJECT_PLANNING_PROFILE_VERSION,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _require_activation(self, project: Project, method: str) -> None:
        if method not in self.explicit_or_inferred_methods(project):
            raise ProjectPlanningError("Метод не обрано для цього проєкту")
        if (
            project.research_design_status != "APPROVED"
            or not self.design_is_current(project)
        ):
            raise ProjectPlanningError("Спочатку затвердьте актуальний дизайн дослідження")

    def _invalidate_design(self, project: Project) -> None:
        if project.current_research_design is not None:
            project.current_research_design = None
            project.research_design_status = None
            project.research_design_input_fingerprint = None
            project.research_design_approved_by = None
            project.research_design_approved_at = None
            project.status = ProjectStatus.LEAD

    def _has_any_activation(self, project_id: str) -> bool:
        return bool(self.workflows.list_workflow_runs_for_project(project_id))

    def _is_activated(self, project_id: str, method: str) -> bool:
        project = self.projects.get_project(project_id)
        if method == DESK:
            return self._desk_run(project_id) is not None
        return QUANTITATIVE in self.explicit_or_inferred_methods(project) and any(
            self.quantitative.state.list_for_run(
                run.id, project_id=project_id, expected_type=self._study_type()
            )
            for run in self.workflows.list_workflow_runs_for_project(project_id)
        )

    def _desk_run(self, project_id: str):
        quant_template = build_quantitative_workflow_template().id
        for run in self.workflows.list_workflow_runs_for_project(project_id):
            if run.workflow_template_id == quant_template:
                continue
            if self.quantitative and self.quantitative.state.list_for_run(
                run.id, project_id=project_id, expected_type=self._study_type()
            ):
                continue
            return run
        return None

    @staticmethod
    def _study_type():
        from domain.quantitative.workflow import QuantitativeStudyProjection
        return QuantitativeStudyProjection
