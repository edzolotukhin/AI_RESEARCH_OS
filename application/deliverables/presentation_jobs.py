"""Durable, source-version-bound PPTX generation state."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PresentationJob:
    id: str
    project_id: str
    method: str
    run_id: str
    study_id: str | None
    source_id: str
    source_version: str
    status_snapshot: str
    template_version: str
    renderer_version: str
    state: str
    attempts: int
    lease_until: datetime | None
    claimed_by: str | None
    created_at: datetime
    updated_at: datetime
    completed_deliverable_id: str | None
    failure_code: str | None
