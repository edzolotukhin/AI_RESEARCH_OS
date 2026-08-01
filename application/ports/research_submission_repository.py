from __future__ import annotations

from abc import ABC, abstractmethod

from application.persistence.records import ResearchSubmissionRecord


class ResearchSubmissionRepository(ABC):
    """Durable idempotent research submission registry."""

    @abstractmethod
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
        """
        Atomically register a submission.

        Returns (created=True, record) on first insert, or
        (created=False, existing_record) when the key already exists.
        """

    @abstractmethod
    def delete_by_key(self, *, project_id: str, idempotency_key: str) -> None:
        """Remove a submission record (e.g. when planning fails before run creation)."""

    @abstractmethod
    def mark_completed(self, *, project_id: str, idempotency_key: str) -> None:
        """Mark a submission completed after WorkflowRun creation succeeds."""

    @abstractmethod
    def get_by_key(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> ResearchSubmissionRecord | None:
        """Load a submission by project and idempotency key."""

    @abstractmethod
    def get_by_run_id(self, run_id: str) -> ResearchSubmissionRecord | None:
        """Load external submission metadata for a workflow run."""
