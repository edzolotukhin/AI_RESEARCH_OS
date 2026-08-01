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
    content_preview: str = Field(
        description="Metadata-only preview; binary blob storage is not implemented.",
    )


class ArtifactListResponse(BaseModel):
    items: list[ArtifactResponse]
    count: int
