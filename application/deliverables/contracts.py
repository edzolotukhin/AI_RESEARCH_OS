"""Source-bound, method-aware PDF input and immutable deliverable metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PdfSection:
    title: str
    paragraphs: tuple[str, ...]
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfTable:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    base: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class PresentationChart:
    title: str
    labels: tuple[str, ...]
    values: tuple[float, ...]
    base: str | None
    unit: str | None
    supported: bool = True


@dataclass(frozen=True)
class PdfSourceDocument:
    project_id: str
    method: str
    run_id: str
    study_id: str | None
    source_id: str
    source_version: str
    status: str
    title: str
    summary: str | None
    sections: tuple[PdfSection, ...]
    limitations: tuple[str, ...]
    tables: tuple[PdfTable, ...] = ()
    citation_registry: tuple[tuple[str, str], ...] = ()
    links: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    created_at: str | None = None
    revision_number: int | None = None
    previous_report_id: str | None = None
    charts: tuple[PresentationChart, ...] = ()


@dataclass(frozen=True)
class PdfDeliverable:
    id: str
    project_id: str
    method: str
    run_id: str
    study_id: str | None
    source_id: str
    source_version: str
    status_snapshot: str
    renderer_version: str
    created_at: datetime
    storage_key: str
    checksum: str
    byte_size: int
    filename: str
    media_type: str = "application/pdf"
    state: str = "completed"
    format: str = "PDF"
    template_version: str = "pdf-v1"


RENDERER_VERSION = "prf06e-reportlab-1"
