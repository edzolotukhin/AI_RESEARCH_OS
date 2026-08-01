from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectBriefRequest(BaseModel):
    client: str = Field(min_length=1, examples=["Purina"])
    project_title: str = Field(min_length=1, examples=["Brand Health 2026"])
    business_problem: str = Field(min_length=1)
    research_goal: str = Field(min_length=1)
    research_objectives: list[str] = Field(default_factory=list)
    research_object: str = ""
    target_audience: str = ""
    geography: str = ""
    constraints: list[str] = Field(default_factory=list)
    timeline: str = ""
    comments: str = ""


class StartResearchRequest(BaseModel):
    brief: ProjectBriefRequest
    correlation_id: str | None = Field(
        default=None,
        description="Business/process correlation identifier for external orchestrators.",
        max_length=256,
    )
    source: str | None = Field(
        default=None,
        description="External caller source label (e.g. n8n).",
        max_length=64,
    )


class TaskResponse(BaseModel):
    id: str
    definition_id: str
    name: str
    status: str
    executor_id: str
    executor_type: str
    depends_on: list[str]


class ExternalSubmissionMetadata(BaseModel):
    correlation_id: str | None = None
    external_request_id: str | None = None
    source: str | None = None
    submitted_at: str | None = None


class WorkflowRunResponse(BaseModel):
    id: str
    project_id: str
    workflow_template_id: str
    status: str
    version: int | None = None
    is_terminal: bool
    tasks: list[TaskResponse]
    results_available: bool = False
    artifacts_available: bool = False
    external: ExternalSubmissionMetadata | None = None


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]
    count: int


class StartResearchResponse(BaseModel):
    run_id: str
    project_id: str
    workflow_template_id: str
    status: str
    is_terminal: bool
    tasks: list[TaskResponse]
    idempotent_replay: bool = False
    external: ExternalSubmissionMetadata | None = None


class TaskResultItem(BaseModel):
    task_id: str
    snapshot: dict[str, Any]


class WorkflowRunResultsResponse(BaseModel):
    run_id: str
    status: str
    is_terminal: bool
    results_ready: bool
    task_results: list[TaskResultItem]


class ExecutionLogResponse(BaseModel):
    event_id: str
    run_id: str
    event_type: str
    timestamp: str
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionLogListResponse(BaseModel):
    items: list[ExecutionLogResponse]
    count: int
