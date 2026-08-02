from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewIssueResponse(BaseModel):
    id: str
    issue_type: str
    severity: str
    message: str
    report_section_id: str | None = None
    finding_refs: list[str] = Field(default_factory=list)
    insight_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    research_question_refs: list[str] = Field(default_factory=list)
    suggested_action: str = ""


class QualityDimensionResponse(BaseModel):
    name: str
    status: str
    message: str = ""


class ReviewResponse(BaseModel):
    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    report_id: str
    artifact_id: str | None = None
    previous_report_id: str | None = None
    review_attempt: int
    verdict: str
    quality_dimensions: list[QualityDimensionResponse]
    issues: list[ReviewIssueResponse]
    summary: str
    review_method: str
    created_at: str


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    count: int
