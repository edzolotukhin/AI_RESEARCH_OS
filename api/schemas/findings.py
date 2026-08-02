from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FindingResponse(BaseModel):
    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    research_question_refs: list[str] = Field(default_factory=list)
    information_need_refs: list[str] = Field(default_factory=list)
    statement: str
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    finding_type: str
    confidence: float | None = None
    analysis_method: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingListResponse(BaseModel):
    items: list[FindingResponse]
    count: int


class InsightResponse(BaseModel):
    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    research_question_refs: list[str] = Field(default_factory=list)
    statement: str
    implication: str
    finding_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    count: int
