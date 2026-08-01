from __future__ import annotations

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Brand Health 2026"])


class ProjectResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    offset: int
    limit: int
    count: int
