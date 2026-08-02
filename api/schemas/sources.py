from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceResponse(BaseModel):
    id: str
    project_id: str
    url: str
    canonical_url: str
    title: str
    publisher: str = ""
    author: str = ""
    published_at: str | None = None
    retrieved_at: str
    source_type: str
    language: str = ""
    content_type: str = ""
    query_refs: list[str] = Field(default_factory=list)
    research_question_refs: list[str] = Field(default_factory=list)
    information_need_refs: list[str] = Field(default_factory=list)
    workflow_run_refs: list[str] = Field(default_factory=list)
    research_design_refs: list[str] = Field(default_factory=list)
    retrieval_status: str
    content_preview: str = ""
    content_checksum: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    count: int
