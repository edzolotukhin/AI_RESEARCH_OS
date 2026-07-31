from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from application.persistence.exceptions import (
    ConcurrentModificationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from application.ports.workflow_run_repository import WorkflowRunRepository
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.postgresql.concurrency import atomic_update_version
from infrastructure.persistence.postgresql.mappers.workflow_run_mapper import (
    workflow_run_from_model,
    workflow_run_to_model,
    workflow_run_to_update_values,
    _task_to_model,
)
from infrastructure.persistence.postgresql.models.task_model import WorkflowTaskModel
from infrastructure.persistence.postgresql.models.workflow_run_model import (
    WorkflowRunModel,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLWorkflowRunRepository:
    """PostgreSQL adapter for WorkflowRun aggregate persistence."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(
        self,
        workflow_run: WorkflowRun,
        *,
        project_id: str,
    ) -> None:
        with self._session_factory.session() as session:
            existing = session.get(WorkflowRunModel, workflow_run.id)
            if existing is not None:
                raise DuplicateEntityError(
                    f"WorkflowRun already exists: {workflow_run.id}"
                )

            stored = workflow_run_to_model(
                workflow_run,
                project_id=project_id,
                version=0,
                task_results={},
            )
            if not workflow_run.project_id:
                stored.project_id = project_id
            session.add(stored)

    def get_by_id(self, run_id: str) -> WorkflowRun | None:
        with self._session_factory.session() as session:
            statement = (
                select(WorkflowRunModel)
                .where(WorkflowRunModel.id == run_id)
                .options(selectinload(WorkflowRunModel.tasks))
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return workflow_run_from_model(model)

    def save(
        self,
        workflow_run: WorkflowRun,
        *,
        expected_version: int | None = None,
        task_results: dict[str, Any] | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            current = session.get(WorkflowRunModel, workflow_run.id)
            if current is None:
                raise EntityNotFoundError(
                    f"WorkflowRun not found: {workflow_run.id}"
                )

            stored_results = dict(current.task_results or {})
            if task_results is not None:
                stored_results = dict(task_results)

            update_values = workflow_run_to_update_values(
                workflow_run,
                task_results=stored_results,
            )
            new_version = atomic_update_version(
                session,
                WorkflowRunModel,
                workflow_run.id,
                expected_version=expected_version,
                values=update_values,
            )

            session.execute(
                delete(WorkflowTaskModel).where(
                    WorkflowTaskModel.workflow_run_id == workflow_run.id,
                )
            )
            for index, task in enumerate(workflow_run.tasks):
                session.add(
                    _task_to_model(
                        task,
                        workflow_run_id=workflow_run.id,
                        sort_order=index,
                    )
                )

            return new_version

    def get_task_results(self, run_id: str) -> dict[str, Any]:
        with self._session_factory.session() as session:
            model = session.get(WorkflowRunModel, run_id)
            if model is None:
                return {}
            return dict(model.task_results or {})

    def list_for_project(
        self,
        project_id: str,
        *,
        status: WorkflowStatus | None = None,
    ) -> list[WorkflowRun]:
        with self._session_factory.session() as session:
            statement = (
                select(WorkflowRunModel)
                .where(WorkflowRunModel.project_id == project_id)
                .options(selectinload(WorkflowRunModel.tasks))
                .order_by(WorkflowRunModel.id)
            )
            if status is not None:
                statement = statement.where(
                    WorkflowRunModel.status == status.value,
                )

            models = session.scalars(statement).all()
            return [workflow_run_from_model(model) for model in models]
