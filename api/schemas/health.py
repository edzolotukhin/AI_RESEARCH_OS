from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str
    version: str
    persistence_backend: str


class ReadinessResponse(BaseModel):
    status: str = Field(examples=["ready"])
    service: str
    persistence_backend: str
    reason: str | None = None
