"""Atomic immutable PDF repository interface and non-durable memory adapter."""

from __future__ import annotations

from threading import Lock
import hashlib
from typing import Protocol

from application.deliverables.contracts import PdfDeliverable


class PdfStore(Protocol):
    def get(self, deliverable_id: str) -> tuple[PdfDeliverable, bytes] | None: ...
    def find(self, *, project_id: str, method: str, source_id: str,
             source_version: str, renderer_version: str,
             format: str = "PDF", template_version: str = "pdf-v1") -> PdfDeliverable | None: ...
    def complete(self, record: PdfDeliverable, data: bytes) -> PdfDeliverable: ...


class InMemoryPdfStore:
    """Development only: atomic per-process, not durable across restarts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_id: dict[str, tuple[PdfDeliverable, bytes]] = {}
        self._by_key: dict[tuple[str, str, str, str, str, str, str], str] = {}

    @staticmethod
    def _key(record: PdfDeliverable) -> tuple[str, str, str, str, str, str, str]:
        return (record.project_id, record.method, record.source_id,
                record.source_version, record.format, record.template_version,
                record.renderer_version)

    def get(self, deliverable_id: str) -> tuple[PdfDeliverable, bytes] | None:
        with self._lock:
            return self._by_id.get(deliverable_id)

    def find(self, *, project_id: str, method: str, source_id: str,
             source_version: str, renderer_version: str,
             format: str = "PDF", template_version: str = "pdf-v1") -> PdfDeliverable | None:
        with self._lock:
            identity = self._by_key.get((project_id, method, source_id, source_version,
                                         format, template_version, renderer_version))
            return self._by_id[identity][0] if identity else None

    def complete(self, record: PdfDeliverable, data: bytes) -> PdfDeliverable:
        expected = (("PDF", "application/pdf", b"%PDF-", 5_000_000),
                    ("PPTX", "application/vnd.openxmlformats-officedocument.presentationml.presentation", b"PK\x03\x04", 10_000_000))
        valid = any(record.format == fmt and record.media_type == media and
                    data.startswith(magic) and 0 < len(data) <= limit
                    for fmt, media, magic, limit in expected)
        if not valid or len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.checksum:
            raise ValueError("invalid completed deliverable content")
        with self._lock:
            key = self._key(record)
            existing = self._by_key.get(key)
            if existing:
                return self._by_id[existing][0]
            self._by_id[record.id] = (record, bytes(data))
            self._by_key[key] = record.id
            return record
