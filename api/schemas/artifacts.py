from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactResponse(BaseModel):
    id: str
    project_id: str
    run_id: str | None = None
    artifact_type: str
    title: str
    status: str
    version: int
    media_type: str = ""
    filename: str = ""
    content_checksum: str = ""
    report_id: str | None = None
    content_preview: str = Field(
        description="Short preview; use GET /artifacts/{id}/content for full body.",
    )


class ArtifactContentResponse(BaseModel):
    id: str
    media_type: str
    filename: str
    content: str
    content_checksum: str


class ArtifactListResponse(BaseModel):
    items: list[ArtifactResponse]
    count: int
