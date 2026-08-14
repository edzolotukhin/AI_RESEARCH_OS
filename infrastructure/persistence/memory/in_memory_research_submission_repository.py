from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from application.persistence.records import (
    ResearchSubmissionRecord,
    ResearchSubmissionStatus,
)
from application.ports.research_submission_repository import ResearchSubmissionRepository


class InMemoryResearchSubmissionRepository(ResearchSubmissionRepository):
    """Embedded/test idempotency store (not durable across process restart)."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], ResearchSubmissionRecord] = {}
        self._by_run_id: dict[str, ResearchSubmissionRecord] = {}
        self._lock = Lock()

    def try_register(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        run_id: str,
        correlation_id: str | None,
        source: str | None,
    ) -> tuple[bool, ResearchSubmissionRecord]:
        key = (project_id, idempotency_key)
        record = ResearchSubmissionRecord(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            run_id=run_id,
            correlation_id=correlation_id,
            source=source,
            created_at=datetime.now(timezone.utc),
            status=ResearchSubmissionStatus.PENDING,
        )
        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None:
                return False, existing
            self._by_key[key] = record
            self._by_run_id[run_id] = record
            return True, record

    def delete_by_key(self, *, project_id: str, idempotency_key: str) -> None:
        key = (project_id, idempotency_key)
        with self._lock:
            existing = self._by_key.pop(key, None)
            if existing is not None:
                self._by_run_id.pop(existing.run_id, None)

    def mark_completed(self, *, project_id: str, idempotency_key: str) -> None:
        key = (project_id, idempotency_key)
        with self._lock:
            existing = self._by_key.get(key)
            if existing is None:
                return
            completed = ResearchSubmissionRecord(
                project_id=existing.project_id,
                idempotency_key=existing.idempotency_key,
                request_fingerprint=existing.request_fingerprint,
                run_id=existing.run_id,
                correlation_id=existing.correlation_id,
                source=existing.source,
                created_at=existing.created_at,
                status=ResearchSubmissionStatus.COMPLETED,
            )
            self._by_key[key] = completed
            self._by_run_id[completed.run_id] = completed

    def mark_failed(self, *, project_id: str, idempotency_key: str) -> None:
        key = (project_id, idempotency_key)
        with self._lock:
            existing = self._by_key.get(key)
            if existing is None:
                return
            failed = ResearchSubmissionRecord(
                project_id=existing.project_id,
                idempotency_key=existing.idempotency_key,
                request_fingerprint=existing.request_fingerprint,
                run_id=existing.run_id,
                correlation_id=existing.correlation_id,
                source=existing.source,
                created_at=existing.created_at,
                status=ResearchSubmissionStatus.FAILED,
            )
            self._by_key[key] = failed
            self._by_run_id[failed.run_id] = failed

    def get_by_key(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> ResearchSubmissionRecord | None:
        key = (project_id, idempotency_key)
        with self._lock:
            return self._by_key.get(key)

    def get_by_run_id(self, run_id: str) -> ResearchSubmissionRecord | None:
        with self._lock:
            return self._by_run_id.get(run_id)
