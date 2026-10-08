from __future__ import annotations

from uuid import uuid4

from api.ui.principal import resolve_ui_principal
from application.query.project_workspace_query_service import ProjectWorkspaceQueryService
from application.query.project_outputs_query_service import ProjectOutputsQueryService
from application.quantitative.workflow import build_quantitative_workflow_template
from application.quantitative.ui_service import QuantitativeUiError
from domain.research_brief import ResearchBrief
from domain.research_method import canonicalize_research_methods


class ProjectWorkspaceFacade:
    def __init__(self, container) -> None:
        self.container = container
        self.principal = resolve_ui_principal(container)
        self.authorization = container.authorization_service
        self.query = ProjectWorkspaceQueryService(
            project_service=container.project_service,
            workflow_service=container.workflow_service,
            quantitative_ui_service=container.quantitative_ui_service,
            research_result_service=container.research_run_result_query_service,
            project_planning_service=container.project_planning_service,
            qualitative_service=container.qualitative_service,
        )

    @property
    def owner_id(self): return self.principal.principal_id
    def list_projects(self):
        projects=self.authorization.list_visible_projects(self.principal)
        items=[]
        from application.query.project_workspace_views import ProjectListItemView, ProjectListView
        for project in projects:
            view=self.query.get(project.id,owner_id=project.owner_principal_id)
            role, _, _ = self._role(project.id)
            next_action = next((m.primary_action.label for m in view.methods if m.state.value != "COMPLETED"), "View outputs")
            items.append(ProjectListItemView(project.id,project.name,self.query._humanize(project.status),tuple((m.name,m.state_label) for m in view.methods),bool(view.attention_items),role,next_action))
        return ProjectListView(tuple(items))
    def create_project(self, name: str, selected_methods):
        name = name.strip()
        if not name: raise ValueError("Вкажіть назву проєкту")
        try:
            methods = canonicalize_research_methods(selected_methods)
        except ValueError as exc:
            raise ValueError("Оберіть щонайменше один метод дослідження") from exc
        project=self.container.project_service.build_project(
            name, owner_principal_id=self.owner_id, selected_methods=methods,
        )
        if self.principal.authentication_type != "browser_session":
            self.container.project_service.persist_built_project(project)
            return project
        from application.identity import ProjectMembership, ProjectRole
        from datetime import UTC, datetime
        membership = ProjectMembership(project.id, self.owner_id, ProjectRole.OWNER,
                                       datetime.now(UTC), self.owner_id)
        atomic_create = getattr(self.container.identity_service.store, "create_owned_project", None)
        if atomic_create is not None:
            atomic_create(project, membership)
            return project
        try:
            self.container.project_service.persist_built_project(project)
            self.container.identity_service.store.create_membership(membership)
        except Exception:
            self.container.project_service.delete_project(project.id)
            raise
        return project
    def _project_owner(self, project_id: str, *, mutate: bool=False, owner: bool=False):
        project=self.authorization.require_project(self.principal,project_id)
        if self.principal.authentication_type == "browser_session":
            self.container.identity_service.require(
                project_id, self.owner_id, mutate=mutate, owner=owner,
            )
        return project,project.owner_principal_id
    def get_workspace(self, project_id: str):
        project,_=self._project_owner(project_id)
        from dataclasses import replace
        role, can_mutate, can_manage = self._role(project_id)
        return replace(self.query.get(project_id, owner_id=project.owner_principal_id),
                       role=role, can_mutate=can_mutate, can_manage_access=can_manage)

    def _role(self, project_id: str):
        if self.principal.authentication_type != "browser_session":
            return "OWNER", True, True
        membership = self.container.identity_service.require(project_id, self.owner_id)
        role = membership.role.value
        return role, role in {"OWNER", "RESEARCHER"}, role == "OWNER"
    def get_outputs(self, project_id: str):
        project = self.authorization.require_project(self.principal, project_id)
        return ProjectOutputsQueryService(container=self.container).get(
            project, owner_id=project.owner_principal_id,
        )
    def get_report_catalog(self, project_id: str):
        _,owner=self._project_owner(project_id); return self.container.project_deliverables_service.catalog(project_id, owner_id=owner)
    def get_report_source(self, project_id: str, method: str, source_id: str):
        _,owner=self._project_owner(project_id); return self.container.project_deliverables_service.source(project_id, method, source_id, owner_id=owner)
    def generate_report_pdf(self, project_id: str, method: str, source_id: str):
        _,owner=self._project_owner(project_id,mutate=True); return self.container.project_deliverables_service.generate(project_id, method, source_id, owner_id=owner)
    def download_report_pdf(self, project_id: str, method: str, source_id: str, deliverable_id: str):
        _,owner=self._project_owner(project_id); return self.container.project_deliverables_service.download(project_id, method, source_id, deliverable_id, owner_id=owner)
    def schedule_presentation(self, project_id: str, method: str, source_id: str):
        _,owner=self._project_owner(project_id,mutate=True); return self.container.project_deliverables_service.schedule_presentation(project_id, method, source_id, owner_id=owner)
    def download_presentation(self, project_id: str, method: str, source_id: str, deliverable_id: str):
        _,owner=self._project_owner(project_id); return self.container.project_deliverables_service.download_presentation(project_id, method, source_id, deliverable_id, owner_id=owner)
    def start_desk(self, project_id: str, brief_payload: dict):
        project = self.authorization.require_project(self.principal, project_id)
        quant_id = build_quantitative_workflow_template().id
        if any(run.workflow_template_id != quant_id for run in self.container.workflow_service.list_workflow_runs_for_project(project_id)):
            raise ValueError("У цьому проєкті вже є кабінетне дослідження")
        brief = ResearchBrief.from_dict(brief_payload)
        if brief is None or not brief.business_question.strip(): raise ValueError("Вкажіть бізнес-питання")
        project.research_brief = brief
        return self.container.agency.start_research(project)

    def save_brief(self, project_id: str, brief_payload: dict):
        project = self.authorization.require_project(self.principal, project_id)
        brief = ResearchBrief.from_dict(brief_payload)
        if brief is None or not brief.business_question.strip():
            raise ValueError("Вкажіть бізнес-питання")
        if not brief.title.strip():
            raise ValueError("Вкажіть назву дослідження")
        return self.container.project_planning_service.save_brief(project, brief)

    def generate_design(self, project_id: str):
        project = self.authorization.require_project(self.principal, project_id)
        return self.container.project_planning_service.generate_design(project)

    def approve_design(self, project_id: str, design_id: str):
        project = self.authorization.require_project(self.principal, project_id)
        return self.container.project_planning_service.approve_design(
            project, actor_id=self.owner_id, expected_design_id=design_id,
        )

    def add_method(self, project_id: str, method: str):
        project = self.authorization.require_project(self.principal, project_id)
        return self.container.project_planning_service.add_method(project, method)

    def remove_method(self, project_id: str, method: str):
        project = self.authorization.require_project(self.principal, project_id)
        return self.container.project_planning_service.remove_method(project, method)

    def activate_method(self, project_id: str, method: str):
        project = self.authorization.require_project(self.principal, project_id)
        if method == "DESK":
            run = self.container.project_planning_service.activate_desk(project)
            return "desk", run.id
        if method == "QUANTITATIVE":
            study = self.container.project_planning_service.activate_quantitative(
                project, owner_id=self.owner_id,
            )
            return "quantitative", study.study_id
        if method == "QUALITATIVE":
            run = self.container.qualitative_service.create_run(project_id, owner_id=self.owner_id)
            return "qualitative", run.record_id
        raise ValueError("Невідомий метод дослідження")

    def retry_desk(self, project_id: str):
        project, _ = self._project_owner(project_id, mutate=True)
        return self.container.project_planning_service.retry_failed_desk(project)

    def project_for_design(self, project_id: str):
        return self.authorization.require_project(self.principal, project_id)
    def create_quantitative(self, project_id: str, title: str, description: str, submission_key: str):
        self.authorization.require_project(self.principal, project_id)
        try:
            return self.container.quantitative_ui_service.create_quantitative_study_for_project(
                project_id=project_id, owner_id=self.owner_id, title=title,
                description=description, submission_key=submission_key.strip() or str(uuid4()),
                canonical=True)
        except QuantitativeUiError as exc:
            translated = {
                "title and submission_key are required": "Вкажіть назву дослідження",
                "Project not found": "Проєкт не знайдено",
                "This Project already has a Quantitative study": "У цьому проєкті вже є кількісне дослідження",
                "Quantitative study not found": "Кількісне дослідження не знайдено",
                "submission key was already used for different content": "Цей ключ подання вже використано для іншого вмісту",
            }.get(str(exc), str(exc))
            raise QuantitativeUiError(translated) from exc


def build_project_workspace_facade(container):
    if container.authorization_service is None: raise RuntimeError("Authorization is not configured for this deployment.")
    return ProjectWorkspaceFacade(container)
