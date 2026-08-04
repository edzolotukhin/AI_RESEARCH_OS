from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from application.execution.exceptions import ClaimConflictError, LeaseLostError
from application.execution.heartbeat import HeartbeatManager, LeaseGuard
from application.execution.lease_config import LeaseConfig
from application.execution.models import ClaimResult
from application.ports.workflow_run_execution_port import WorkflowRunExecutionPort
from application.services.durable_workflow_service import DurableWorkflowService

logger = logging.getLogger("ai_research_os.worker")


class WorkerExecutionService:
    """
    Coordinates claim, lease heartbeat, and durable workflow execution.

    Business orchestration remains in DurableWorkflowService / WorkflowEngine.
    """

    def __init__(
        self,
        *,
        durable_workflow_service: DurableWorkflowService,
        execution_port: WorkflowRunExecutionPort,
        lease_config: LeaseConfig | None = None,
    ) -> None:
        self._durable_workflow_service = durable_workflow_service
        self._execution_port = execution_port
        self._lease_config = lease_config or LeaseConfig()
        self._last_run_error: Exception | None = None

    def process_once(self, worker_id: str) -> bool:
        """Claim and execute at most one runnable run. Returns True if work ran."""
        self._last_run_error = None
        try:
            claim = self._claim_next(worker_id)
        except Exception:
            logger.exception(
                "worker_claim_query_failed worker_id=%s",
                worker_id,
            )
            return False
        if claim is None:
            return False
        logger.info(
            "worker_claim_success run_id=%s worker_id=%s",
            claim.run_id,
            worker_id,
        )
        try:
            self.execute_claimed_run(claim, worker_id)
        except LeaseLostError:
            logger.warning(
                "worker_lease_lost run_id=%s worker_id=%s",
                claim.run_id,
                worker_id,
            )
            return True
        except Exception as exc:
            self._last_run_error = exc
            logger.exception(
                "worker_execute_failed run_id=%s worker_id=%s",
                claim.run_id,
                worker_id,
            )
            return True
        return True

    def execute_claimed_run(self, claim: ClaimResult, worker_id: str) -> None:
        lease_guard = LeaseGuard()
        try:
            with HeartbeatManager(
                execution_port=self._execution_port,
                run_id=claim.run_id,
                worker_id=worker_id,
                lease_config=self._lease_config,
                initial_version=claim.version,
                lease_guard=lease_guard,
            ):
                self._durable_workflow_service.execute_claimed_run(
                    claim.run_id,
                    worker_id=worker_id,
                    lease_guard=lease_guard,
                )
        except LeaseLostError:
            return
        finally:
            try:
                self._execution_port.release_lease(
                    claim.run_id,
                    worker_id=worker_id,
                )
            except (ClaimConflictError, Exception):
                pass

    def drain_runnable_runs(self, worker_id: str, *, max_runs: int = 100) -> int:
        """Process runnable runs until none remain or max_runs is reached."""
        processed = 0
        for _ in range(max_runs):
            if not self.process_once(worker_id):
                break
            processed += 1
            if self._last_run_error is not None:
                error = self._last_run_error
                self._last_run_error = None
                raise error
        return processed

    def _claim_next(self, worker_id: str) -> ClaimResult | None:
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=self._lease_config.lease_duration_seconds)
        return self._execution_port.claim_next_runnable(
            worker_id=worker_id,
            lease_until=lease_until,
            now=now,
        )
