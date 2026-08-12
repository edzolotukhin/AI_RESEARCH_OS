"""Public Research API DTOs (P1-19.1 thin facade)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from api.schemas.workflow_runs import ResearchBriefRequest
from domain.research_brief import ResearchBrief


class PublicResearchBriefRequest(ResearchBriefRequest):
    """User-facing Brief DTO — same fields as ResearchBriefRequest."""


class SubmitResearchRequest(BaseModel):
    brief: PublicResearchBriefRequest
    project_id: str | None = Field(
        default=None,
        description="Optional existing project. When omitted, a project is created.",
    )
    correlation_id: str | None = Field(default=None, max_length=256)
    source: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_brief_wrapper(cls, data: object) -> object:
        if isinstance(data, dict) and "brief" in data and isinstance(data["brief"], dict):
            brief = data["brief"]
            if "business_problem" in brief or "project_title" in brief:
                data = dict(data)
                data["brief"] = ResearchBrief.from_dict(brief).to_dict()
        return data


class ResearchStatusResponse(BaseModel):
    research_id: str
    run_id: str
    project_id: str
    execution_status: str
    phase: str
    product_outcome: str | None = None
    result_available: bool = False
    workflow_status: str | None = None
    status_url: str
    result_url: str


class ResearchSubmissionResponse(ResearchStatusResponse):
    """202 response after Research submit."""


class ResearchResultResponse(BaseModel):
    """Thin serializer over P1-18.1 ResearchRunResult.to_dict()."""

    research_id: str
    run_id: str
    project_id: str
    correlation_id: str | None = None
    workflow_status: str
    outcome: str
    readiness: dict[str, Any]
    termination_reason: str | None = None
    limitations: list[str]
    budget_usage: dict[str, Any]
    source_summary: dict[str, Any]
    evidence_summary: dict[str, Any]
    finding_summary: dict[str, Any]
    insight_summary: dict[str, Any]
    latest_report: dict[str, Any] | None = None
    latest_review: dict[str, Any] | None = None
    artifact_status: dict[str, Any]
    provenance_summary: dict[str, Any]

    @classmethod
    def from_result_dict(cls, payload: dict[str, Any]) -> ResearchResultResponse:
        data = dict(payload)
        data["research_id"] = data.get("run_id", "")
        return cls.model_validate(data)
