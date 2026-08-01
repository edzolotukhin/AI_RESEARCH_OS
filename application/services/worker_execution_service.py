from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application.execution.exceptions import ClaimConflictError, LeaseLostError
from application.execution.heartbeat import HeartbeatManager, LeaseGuard
from application.execution.lease_config import LeaseConfig
from application.execution.models import ClaimResult
from application.ports.workflow_run_execution_port import WorkflowRunExecutionPort
from application.services.durable_workflow_service import DurableWorkflowService


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

    def process_once(self, worker_id: str) -> bool:
        """Claim and execute at most one runnable run. Returns True if work ran."""
        claim = self._claim_next(worker_id)
        if claim is None:
            return False
        self.execute_claimed_run(claim, worker_id)
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
        return processed

    def _claim_next(self, worker_id: str) -> ClaimResult | None:
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=self._lease_config.lease_duration_seconds)
        return self._execution_port.claim_next_runnable(
            worker_id=worker_id,
            lease_until=lease_until,
            now=now,
        )
