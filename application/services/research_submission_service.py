from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from application.persistence.exceptions import IdempotencyConflictError, EntityNotFoundError
from application.persistence.records import (
    ResearchSubmissionRecord,
    ResearchSubmissionStatus,
)
from application.ports.research_submission_repository import ResearchSubmissionRepository
from domain.workflow_run import WorkflowRun

RECONCILE_MAX_ATTEMPTS = 100
RECONCILE_POLL_INTERVAL_SECONDS = 0.01


@dataclass(frozen=True)
class IdempotentResearchSubmissionResult:
    created: bool
    run_id: str
    replay: bool
    submission: ResearchSubmissionRecord | None = None


class ResearchSubmissionService:
    """Coordinates durable idempotent research submission for external callers."""

    def __init__(
        self,
        *,
        submission_repository: ResearchSubmissionRepository | None,
    ) -> None:
        self._submission_repository = submission_repository

    @property
    def enabled(self) -> bool:
        return self._submission_repository is not None

    def resolve_submission(
        self,
        *,
        project_id: str,
        idempotency_key: str | None,
        request_fingerprint: str,
        correlation_id: str | None,
        source: str | None,
    ) -> IdempotentResearchSubmissionResult:
        if not idempotency_key or self._submission_repository is None:
            return IdempotentResearchSubmissionResult(
                created=True,
                run_id=str(uuid4()),
                replay=False,
                submission=None,
            )

        run_id = str(uuid4())
        created, record = self._submission_repository.try_register(
            project_id=project_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            run_id=run_id,
            correlation_id=correlation_id,
            source=source,
        )
        if not created and record.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} was already used with a "
                "different research request."
            )
        return IdempotentResearchSubmissionResult(
            created=created,
            run_id=record.run_id,
            replay=(
                not created
                and record.status == ResearchSubmissionStatus.COMPLETED
            ),
            submission=record,
        )

    def mark_completed(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> None:
        if self._submission_repository is None:
            return
        self._submission_repository.mark_completed(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    def mark_failed(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> None:
        if self._submission_repository is None:
            return
        self._submission_repository.mark_failed(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    def get_submission(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> ResearchSubmissionRecord | None:
        if self._submission_repository is None:
            return None
        return self._submission_repository.get_by_key(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    def resolve_visible_run(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        run_id: str,
        load_workflow_run: Callable[[str], WorkflowRun],
    ) -> WorkflowRun | None:
        """Return a durable run when submission completion is already visible."""
        return self._resolve_visible_run(
            project_id=project_id,
            idempotency_key=idempotency_key,
            run_id=run_id,
            load_workflow_run=load_workflow_run,
        )

    def wait_for_peer_completion(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        run_id: str,
        load_workflow_run: Callable[[str], WorkflowRun],
    ) -> WorkflowRun | None:
        """
        Wait for the winning concurrent submission to finish.

        Returns the durable WorkflowRun when the peer completes or the run
        becomes visible. Returns None when no progress is observed within the
        bounded reconciliation window and this request should take over.
        """
        if self._submission_repository is None:
            return None

        for attempt in range(RECONCILE_MAX_ATTEMPTS):
            resolved = self._resolve_visible_run(
                project_id=project_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
                load_workflow_run=load_workflow_run,
            )
            if resolved is not None:
                return resolved
            if attempt + 1 < RECONCILE_MAX_ATTEMPTS:
                time.sleep(RECONCILE_POLL_INTERVAL_SECONDS)
        return None

    def _resolve_visible_run(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        run_id: str,
        load_workflow_run: Callable[[str], WorkflowRun],
    ) -> WorkflowRun | None:
        if self._submission_repository is None:
            return None

        record = self._submission_repository.get_by_key(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if record is None:
            return None
        if record.status == ResearchSubmissionStatus.COMPLETED:
            return load_workflow_run(record.run_id)

        try:
            existing = load_workflow_run(run_id)
        except EntityNotFoundError:
            return None

        self.mark_completed(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        return existing

    def rollback_submission(
        self,
        *,
        project_id: str,
        idempotency_key: str,
    ) -> None:
        if self._submission_repository is None:
            return
        self._submission_repository.delete_by_key(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    def get_submission_for_run(self, run_id: str) -> ResearchSubmissionRecord | None:
        if self._submission_repository is None:
            return None
        return self._submission_repository.get_by_run_id(run_id)
