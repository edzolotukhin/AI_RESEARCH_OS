from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from domain.research_brief import ResearchBrief


class ResearchBriefRequest(BaseModel):
    title: str = ""
    business_question: str = ""
    objectives: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    market: str = ""
    target_entities: list[str] = Field(default_factory=list)
    timeframe: str = ""
    constraints: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    language: str = Field(default="en", min_length=2, max_length=16)
    context: str = ""
    known_information: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_brief(cls, data: object) -> object:
        if isinstance(data, dict) and (
            "business_problem" in data or "project_title" in data
        ):
            return ResearchBrief.from_dict(data).to_dict()
        return data


class ResearchBriefResponse(BaseModel):
    title: str
    business_question: str
    objectives: list[str]
    geography: list[str]
    market: str
    target_entities: list[str]
    timeframe: str
    constraints: list[str]
    deliverables: list[str]
    language: str
    context: str
    known_information: list[str]
    exclusions: list[str]


class ResearchQuestionResponse(BaseModel):
    id: str
    question: str
    objective_refs: list[str]
    priority: int
    rationale: str


class InformationNeedResponse(BaseModel):
    id: str
    research_question_id: str
    description: str
    priority: int
    preferred_source_types: list[str]
    timeframe: str
    geography: str


class ResearchDesignResponse(BaseModel):
    id: str
    research_questions: list[ResearchQuestionResponse]
    information_needs: list[InformationNeedResponse]
    source_strategy: list[str]
    analysis_plan: list[str]
    deliverable_plan: list[str]
    assumptions: list[str]
    limitations: list[str]
    language: str


class StartResearchRequest(BaseModel):
    brief: ResearchBriefRequest
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
    artifact_count: int = 0
    reports_available: bool = False
    report_count: int = 0
    sources_available: bool = False
    source_count: int = 0
    evidence_available: bool = False
    evidence_count: int = 0
    findings_available: bool = False
    finding_count: int = 0
    insights_available: bool = False
    insight_count: int = 0
    reviews_available: bool = False
    review_count: int = 0
    final_review_verdict: str | None = None
    final_artifact_available: bool = False
    final_artifact_id: str | None = None
    external: ExternalSubmissionMetadata | None = None
    research_brief: ResearchBriefResponse | None = None
    research_design: ResearchDesignResponse | None = None


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
    research_brief: ResearchBriefResponse | None = None
    research_design: ResearchDesignResponse | None = None


class TaskResultItem(BaseModel):
    task_id: str
    snapshot: dict[str, Any]


class WorkflowRunResultsResponse(BaseModel):
    run_id: str
    status: str
    is_terminal: bool
    results_ready: bool
    task_results: list[TaskResultItem]
    research_readiness: dict[str, Any] | None = None


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
