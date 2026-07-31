from __future__ import annotations

from dataclasses import asdict

from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.models.workflow_template_model import (
    WorkflowTemplateModel,
)


def workflow_template_to_model(
    template: WorkflowTemplate,
    *,
    project_id: str,
    created_at,
) -> WorkflowTemplateModel:
    return WorkflowTemplateModel(
        id=template.id,
        project_id=project_id,
        name=template.name,
        snapshot_data={
            "name": template.name,
            "task_definitions": [
                _task_definition_to_dict(definition)
                for definition in template.task_definitions
            ],
        },
        created_at=created_at,
    )


def workflow_template_from_model(model: WorkflowTemplateModel) -> WorkflowTemplate:
    snapshot = model.snapshot_data or {}
    definitions = [
        _task_definition_from_dict(payload)
        for payload in snapshot.get("task_definitions", [])
    ]
    return WorkflowTemplate(
        id=model.id,
        name=snapshot.get("name", model.name),
        task_definitions=definitions,
    )


def _task_definition_to_dict(definition: TaskDefinition) -> dict:
    payload = asdict(definition)
    payload["executor_type"] = definition.executor_type.value
    return payload


def _task_definition_from_dict(payload: dict) -> TaskDefinition:
    executor_type = payload.get("executor_type", ExecutorType.AGENT)
    if isinstance(executor_type, str):
        executor_type = ExecutorType(executor_type)
    return TaskDefinition(
        id=payload["id"],
        name=payload["name"],
        executor_id=payload["executor_id"],
        executor_type=executor_type,
        depends_on=list(payload.get("depends_on", [])),
        metadata=dict(payload.get("metadata", {})),
    )
