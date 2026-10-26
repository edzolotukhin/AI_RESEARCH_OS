from __future__ import annotations

from datetime import UTC, datetime
from contextlib import nullcontext
from dataclasses import dataclass, replace
import heapq
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from application.persistence.exceptions import EntityNotFoundError
from application.planner.project_planning_profile import (
    PROJECT_PLANNING_PROFILE_VERSION,
    PROJECT_PLANNING_PROFILE_KEY,
    ProjectPlanningProfile,
)
from application.research.design_validator import validate_research_design, validate_subject_for_approval
from domain.project import Project
from domain.common.exceptions import ValidationError
from domain.research_brief import ResearchBrief
from domain.research_method import (
    DESK,
    QUANTITATIVE,
    SUPPORTED_RESEARCH_METHODS,
    canonicalize_research_methods,
)
from domain.value_objects.project_status import ProjectStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext
from application.workflow_kind import (
    WorkflowKind,
    classify_workflow_template,
    classify_workflow_template_id,
)


@dataclass(frozen=True)
class DesignGenerationResolution:
    input_fingerprint: str
    state: str
    current_attempt: WorkflowRun | None
    current_design: object | None
    historical_attempts: tuple[WorkflowRun, ...]


class ProjectPlanningError(ValueError):
    pass


class ProjectPlanningService:
    """Owns PF-02 project intent, design gate, and method activation."""

    def __init__(self, *, project_service, workflow_service, planner_agent,
                 workflow_mapper, agency, quantitative_ui_service,
                 activation_sessions=None, file_activation_unavailable=False,
                 durable_workflow_service=None) -> None:
        self.projects = project_service
        self.workflows = workflow_service
        self.planner = planner_agent
        self.workflow_mapper = workflow_mapper
        self.agency = agency
        self.quantitative = quantitative_ui_service
        self.activation_sessions = activation_sessions
        self.file_activation_unavailable = file_activation_unavailable
        self.durable_workflow = durable_workflow_service

    def explicit_or_inferred_methods(self, project: Project) -> tuple[str, ...]:
        if project.selected_methods is not None:
            return canonicalize_research_methods(project.selected_methods, allow_empty=True)
        found: list[str] = []
        for run in self.workflows.list_workflow_runs_for_project(project.id):
            kind = self._workflow_kind(run)
            if kind == WorkflowKind.PROJECT_DESIGN:
                continue
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
            elif not quantitative and kind == WorkflowKind.DESK and DESK not in found:
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
            and self._design_is_resolved(project.current_research_design)
        ):
            return project.current_research_design
        if self._has_any_activation(project.id) and all(
            self._is_activated(project.id, method) for method in methods
        ):
            raise ProjectPlanningError("Дизайн не можна переформувати після активації методу")
        return self._generate_new_design(project, methods=methods, fingerprint=fingerprint)

    def schedule_design_generation(self, project: Project):
        """Queue one durable planning task for the current brief fingerprint."""
        methods = self.explicit_or_inferred_methods(project)
        if not methods:
            raise ProjectPlanningError("Оберіть щонайменше один метод дослідження")
        if project.research_brief is None:
            raise ProjectPlanningError("Спочатку збережіть дослідницький бриф")
        fingerprint = self.input_fingerprint(project.research_brief, methods)
        if (
            project.current_research_design is not None
            and project.research_design_input_fingerprint == fingerprint
            and self.design_is_current(project)
            and self._design_is_resolved(project.current_research_design)
        ):
            return None
        resolution = self.resolve_design_generation(project)
        if resolution.state == "active" and resolution.current_attempt is not None:
            return resolution.current_attempt
        template_id = f"project-design:{project.id}:{fingerprint}"
        template = WorkflowTemplate(
            id=template_id,
            name="Project design generation",
            task_definitions=[TaskDefinition(
                id="task-generate-project-design",
                name="Generate project design",
                executor_id="design_generation",
                executor_type=ExecutorType.AGENT,
            )],
            research_brief_snapshot=project.research_brief,
        )
        if self.durable_workflow is None:
            return self._generate_new_design(project, methods=methods, fingerprint=fingerprint)
        return self.durable_workflow.submit_research(
            project, template, initial_task_results={
                "design_generation": {
                    "version": 1, "project_id": project.id,
                    "input_fingerprint": fingerprint, "status": "queued",
                }
            },
        ).workflow_run

    def resolve_design_generation(self, project: Project) -> DesignGenerationResolution:
        """Resolve the one current-input generation attempt and its durable history."""
        methods = self.explicit_or_inferred_methods(project)
        fingerprint = self.input_fingerprint(project.research_brief, methods)
        return self.resolve_design_generation_attempts(
            project=project,
            workflows=self.workflows,
            input_fingerprint=fingerprint,
        )

    @classmethod
    def resolve_design_generation_attempts(
        cls, *, project: Project, workflows, input_fingerprint: str,
    ) -> DesignGenerationResolution:
        """Canonical attempt resolver shared by scheduling and worker ownership checks."""
        attempts = [
            run for run in workflows.list_workflow_runs_for_project(project.id)
            if classify_workflow_template_id(str(run.workflow_template_id))
            == WorkflowKind.PROJECT_DESIGN
        ]
        attempts.sort(key=cls._design_attempt_order_key)
        matching = [
            run for run in attempts
            if cls._design_attempt_fingerprint(run) == input_fingerprint
        ]
        current = matching[-1] if matching else None
        historical = tuple(run for run in attempts if run is not current)
        if current is None:
            state = "no_attempt"
        elif not current.is_terminal:
            state = "active"
        elif current.status == WorkflowStatus.COMPLETED:
            state = "completed"
        elif current.status == WorkflowStatus.FAILED:
            state = "failed"
        else:
            state = "terminal"
        return DesignGenerationResolution(
            input_fingerprint=input_fingerprint,
            state=state,
            current_attempt=current,
            current_design=project.current_research_design,
            historical_attempts=historical,
        )

    def regenerate_design_after_terminal_run(
        self, project: Project, *, expected_design_id: str,
    ):
        """Create a new draft design while preserving terminal run snapshots."""
        boundary = (
            self.activation_sessions.activation(project.id)
            if self.activation_sessions is not None else nullcontext()
        )
        with boundary:
            if self.activation_sessions is not None:
                project = self.projects.get_project(project.id)
            design = project.current_research_design
            if design is None or design.id != expected_design_id:
                raise ProjectPlanningError("Дизайн змінився; оновіть сторінку")
            eligible, reason = self.design_regeneration_eligibility(project)
            if not eligible:
                raise ProjectPlanningError(reason)
            methods = self.explicit_or_inferred_methods(project)
            return self._generate_new_design(
                project,
                methods=methods,
                fingerprint=self.input_fingerprint(project.research_brief, methods),
            )

    def design_regeneration_eligibility(self, project: Project) -> tuple[bool, str]:
        design = project.current_research_design
        if design is None:
            return False, "Поточний дизайн дослідження відсутній"
        if project.research_design_status not in {"APPROVED", "DRAFT"}:
            return False, "Нову ревізію можна створити лише для затвердженого дизайну"
        if not self.design_is_current(project):
            return False, "Поточний дизайн потребує оновлення"

        bound_runs = []
        historical_design_runs = []
        for run in self.workflows.list_workflow_runs_for_project(project.id):
            try:
                template = self.workflows.get_template(run.workflow_template_id)
            except EntityNotFoundError:
                if not run.is_terminal:
                    return False, "Дочекайтеся завершення активного дослідження"
                continue
            if not run.is_terminal:
                return False, "Дочекайтеся завершення активного дослідження"
            snapshot = template.research_design_snapshot
            if snapshot is not None and snapshot.id == design.id:
                bound_runs.append(run)
            elif snapshot is not None:
                historical_design_runs.append(run)
        if project.research_design_status == "APPROVED":
            if not bound_runs:
                return False, "Немає завершеного дослідження для поточного дизайну"
        elif bound_runs or not historical_design_runs:
            return False, "Чернетка не належить до завершеного циклу ревізії дизайну"
        return True, ""

    def _generate_new_design(self, project: Project, *, methods, fingerprint):
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
        try:
            validate_research_design(design, brief=project.research_brief)
            if DESK in self.explicit_or_inferred_methods(project):
                validate_subject_for_approval(design)
        except (ValidationError, ValueError) as exc:
            raise ProjectPlanningError(str(exc)) from exc
        if project.research_design_status == "APPROVED":
            return project
        if design.research_subject is not None and design.research_subject.resolution_status.value != "unresolved":
            project.current_research_design = replace(
                design,
                research_subject=design.research_subject.approve(),
            )
        project.research_design_status = "APPROVED"
        project.research_design_approved_by = actor_id
        project.research_design_approved_at = datetime.now(UTC).isoformat()
        project.status = ProjectStatus.APPROVED
        self.projects.save_project(project)
        return project

    def activate_desk(self, project: Project):
        if self.file_activation_unavailable:
            raise ProjectPlanningError(
                "Атомарна активація недоступна у файловому режимі зберігання"
            )
        if (
            getattr(self.activation_sessions, "transactional", False)
            and not self.agency._background_execution_enabled
        ):
            raise ProjectPlanningError(
                "Атомарна активація кабінетного дослідження потребує фонового виконання"
            )
        boundary = (
            self.activation_sessions.activation(project.id)
            if self.activation_sessions is not None else nullcontext()
        )
        with boundary:
            if self.activation_sessions is not None:
                project = self.projects.get_project(project.id)
            return self._activate_desk_locked(project)

    def _activate_desk_locked(self, project: Project):
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

    def retry_failed_desk(self, project: Project):
        """Create one immutable replacement for the current failed Desk run."""
        return self.replace_terminal_desk(project, failed_only=True)

    def replace_terminal_desk(self, project: Project, *, failed_only: bool = False):
        """Create one immutable replacement for the current terminal Desk run."""
        if self.file_activation_unavailable:
            raise ProjectPlanningError(
                "Повторний запуск недоступний у файловому режимі зберігання"
            )
        boundary = (
            self.activation_sessions.activation(project.id)
            if self.activation_sessions is not None else nullcontext()
        )
        with boundary:
            if self.activation_sessions is not None:
                project = self.projects.get_project(project.id)
            self._require_activation(project, DESK)
            runs = self._desk_runs(project.id)
            if not runs:
                raise ProjectPlanningError("Немає завершеного запуску для повторення")

            current = runs[-1]
            eligible = {"failed"} if failed_only else {"completed", "failed", "cancelled"}
            if current.status.value not in eligible and len(runs) >= 2:
                predecessor = runs[-2]
                predecessor_eligible = predecessor.status.value in eligible
                expected = self._desk_replacement_run_id(project.id, predecessor.id)
                legacy_expected = self._desk_retry_run_id(project.id, predecessor.id)
                if predecessor_eligible and current.id in {expected, legacy_expected}:
                    return current

            if current.status.value not in eligible:
                raise ProjectPlanningError(
                    "Новий запуск можна створити лише після завершення попереднього"
                )

            template = self.workflow_mapper.from_research_design(
                project.current_research_design,
                project,
            )
            return self.agency.start_research_from_template(
                project,
                template,
                run_id=(
                    self._desk_retry_run_id(project.id, current.id)
                    if failed_only
                    else self._desk_replacement_run_id(project.id, current.id)
                ),
            ).workflow_run

    def can_replace_terminal_desk(self, project_id: str, run_id: str) -> bool:
        current = self._desk_run(project_id)
        return bool(
            current
            and current.id == run_id
            and current.status.value in {"completed", "failed", "cancelled"}
        )

    def activate_quantitative(self, project: Project, *, owner_id: str):
        if self.file_activation_unavailable:
            raise ProjectPlanningError(
                "Атомарна активація недоступна у файловому режимі зберігання"
            )
        boundary = (
            self.activation_sessions.activation(project.id)
            if self.activation_sessions is not None else nullcontext()
        )
        with boundary:
            if self.activation_sessions is not None:
                project = self.projects.get_project(project.id)
            self._require_activation(project, QUANTITATIVE)
            return self.quantitative.create_quantitative_study_for_project(
                project_id=project.id,
                owner_id=owner_id,
                title=f"{project.name} — кількісне дослідження",
                description="Кількісне дослідження в межах проєкту",
                submission_key="pf02-project-activation",
                canonical=True,
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
        if method == DESK:
            try:
                validate_research_design(
                    project.current_research_design, brief=project.research_brief,
                )
                validate_subject_for_approval(project.current_research_design)
                if not project.current_research_design.research_subject.executable:
                    raise ValidationError("Затверджений предмет дослідження не готовий до виконання")
            except (ValidationError, ValueError) as exc:
                raise ProjectPlanningError(str(exc)) from exc

    def _invalidate_design(self, project: Project) -> None:
        if project.current_research_design is not None:
            project.current_research_design = None
            project.research_design_status = None
            project.research_design_input_fingerprint = None
            project.research_design_approved_by = None
            project.research_design_approved_at = None
            project.status = ProjectStatus.LEAD

    def _has_any_activation(self, project_id: str) -> bool:
        return any(
            self._workflow_kind(run) in {
                WorkflowKind.DESK, WorkflowKind.QUANTITATIVE, WorkflowKind.QUALITATIVE,
            }
            for run in self.workflows.list_workflow_runs_for_project(project_id)
        )

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
        runs = self._desk_runs(project_id)
        return runs[-1] if runs else None

    def _desk_runs(self, project_id: str):
        result = []
        for run in self.workflows.list_workflow_runs_for_project(project_id):
            if self._workflow_kind(run) == WorkflowKind.DESK:
                result.append(run)
        return self._order_desk_attempts(result, project_id)

    def _workflow_kind(self, run) -> WorkflowKind:
        identity_kind = classify_workflow_template_id(str(run.workflow_template_id))
        if identity_kind != WorkflowKind.UNKNOWN:
            return identity_kind
        try:
            template = self.workflows.get_template(run.workflow_template_id)
        except (EntityNotFoundError, AttributeError):
            return WorkflowKind.UNKNOWN
        return classify_workflow_template(template)

    @staticmethod
    def _design_attempt_fingerprint(run) -> str:
        template_id = str(run.workflow_template_id)
        return template_id.rsplit(":", 1)[-1] if template_id.startswith("project-design:") else ""

    @classmethod
    def _design_attempt_order_key(cls, run):
        return (cls._desk_attempt_created_at(run), run.id)

    @staticmethod
    def _design_is_resolved(design) -> bool:
        subject = getattr(design, "research_subject", None)
        resolution_status = getattr(subject, "resolution_status", None)
        return (
            subject is None
            or getattr(resolution_status, "value", resolution_status) != "unresolved"
        )

    @classmethod
    def _order_desk_attempts(cls, runs, project_id: str):
        """Order attempts by their persisted replacement lineage.

        OW-03/OW-17 replacement identities encode the predecessor run ID.
        Reconstructing that relationship makes lifecycle order independent of
        equal task timestamps, repository insertion order, and UUID sorting.
        Timestamps remain only a compatibility order between unrelated legacy
        roots for which no replacement relationship was persisted.
        """
        runs = tuple(runs)
        by_id = {run.id: run for run in runs}
        children_by_id = {run.id: [] for run in runs}
        indegree = {run.id: 0 for run in runs}
        for parent in runs:
            for child_id in (
                cls._desk_retry_run_id(project_id, parent.id),
                cls._desk_replacement_run_id(project_id, parent.id),
            ):
                if child_id in by_id:
                    children_by_id[parent.id].append(child_id)
                    indegree[child_id] += 1

        # Stable Kahn ordering preserves each explicit predecessor edge while
        # retaining timestamp compatibility among unrelated historical roots.
        available = [
            (cls._desk_attempt_created_at(run), run.id)
            for run in runs if indegree[run.id] == 0
        ]
        heapq.heapify(available)
        ordered = []
        while available:
            _, run_id = heapq.heappop(available)
            ordered.append(by_id[run_id])
            for child_id in sorted(children_by_id[run_id]):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    child = by_id[child_id]
                    heapq.heappush(
                        available,
                        (cls._desk_attempt_created_at(child), child.id),
                    )
        if len(ordered) != len(runs):
            raise ProjectPlanningError("Виявлено циклічну історію запусків Desk")
        return ordered

    @staticmethod
    def _desk_attempt_created_at(run):
        created_at = min(
            (
                task.created_at
                for task in getattr(run, "tasks", ())
                if getattr(task, "created_at", "")
            ),
            default="",
        )
        return created_at

    @staticmethod
    def _desk_retry_run_id(project_id: str, failed_run_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"ow03-desk-retry:{project_id}:{failed_run_id}"))

    @staticmethod
    def _desk_replacement_run_id(project_id: str, terminal_run_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"ow17-desk-replacement:{project_id}:{terminal_run_id}"))

    @staticmethod
    def _study_type():
        from domain.quantitative.workflow import QuantitativeStudyProjection
        return QuantitativeStudyProjection
