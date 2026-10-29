from __future__ import annotations

from pydantic import BaseModel, Field


class ReportSectionResponse(BaseModel):
    id: str
    title: str
    content: str
    research_question_refs: list[str] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)
    insight_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    id: str
    project_id: str
    workflow_run_id: str
    research_design_id: str
    title: str
    language: str
    sections: list[ReportSectionResponse]
    executive_summary: str
    limitations: list[str] = Field(default_factory=list)
    created_at: str
    generation_method: str
    finding_refs: list[str] = Field(default_factory=list)
    insight_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    citation_registry: dict[str, dict] = Field(default_factory=dict)
    report_contract_version: str | None = None
    revision_number: int | None = None
    authority_digest: str | None = None
    presentation_digest: str | None = None
    references: list[str] = Field(default_factory=list)
    delivery_available: bool = True


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
    count: int
