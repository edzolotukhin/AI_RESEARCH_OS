from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceResponse(BaseModel):
    id: str
    project_id: str
    source_id: str
    source_content_checksum: str
    workflow_run_id: str
    research_design_id: str
    research_question_refs: list[str] = Field(default_factory=list)
    information_need_refs: list[str] = Field(default_factory=list)
    evidence_type: str
    statement: str
    source_excerpt: str
    source_locator: dict[str, Any] = Field(default_factory=dict)
    extraction_method: str
    confidence: float | None = None
    quality_signals: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    count: int
