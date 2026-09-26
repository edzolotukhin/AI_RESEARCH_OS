"""Dedicated kernel JSONB slot with lease check and revision CAS under row lock.

Each execution incarnation installs a token before observing the ledger. A newer
incarnation invalidates stale writers even when the process worker ID is reused.
Pending dispatch is never replayed. No exactly-once external billing is promised.
"""
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from uuid import uuid4

from application.execution.exceptions import LeaseLostError
from application.persistence.exceptions import ConcurrentModificationError
from application.research_kernel.codec import decode, encode
from application.research_kernel.checkpoint import validate_transition
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel

from infrastructure.persistence.postgresql.kernel_ownership import KEY, FENCE


class PostgreSQLKernelStateStore:
    def __init__(self, engine, *, run_id: str, project_id: str, worker_id: str):
        if not all((run_id, project_id, worker_id)):
            raise ValueError("run/project/worker scope required")
        self.engine = engine
        self.run_id, self.project_id, self.worker_id = run_id, project_id, worker_id
        self._fence = str(uuid4())
        self._acquired = False

    def _row(self, session):
        # An outer transaction retaining the run row must fail closed instead
        # of deadlocking the worker before durable reservation/dispatch.
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        row = session.scalar(select(WorkflowRunModel).where(
            WorkflowRunModel.id == self.run_id,
            WorkflowRunModel.project_id == self.project_id,
        ).with_for_update())
        now = session.scalar(select(func.clock_timestamp()))
        if (row is None or row.claimed_by != self.worker_id
                or row.lease_expires_at is None or row.lease_expires_at <= now
                or row.status not in ("created", "running")):
            raise LeaseLostError("kernel requires a current run lease")
        return row

    def load(self):
        # Independent transaction: a caller's open unit of work cannot delay the
        # reservation commit until after a provider call.
        with Session(self.engine) as session, session.begin():
            row = self._row(session)
            results = dict(row.task_results or {})
            if not self._acquired:
                results[FENCE] = {"token": self._fence, "dispatch": None}
                row.task_results = results
            elif results.get(FENCE, {}).get("token") != self._fence:
                raise LeaseLostError("kernel execution incarnation superseded")
            payload = (row.task_results or {}).get(KEY)
            state = decode(payload) if payload is not None else None
        self._acquired = True
        return state

    def authorize_dispatch(self, state):
        with Session(self.engine) as session, session.begin():
            row = self._row(session)
            results = row.task_results or {}
            if not self._acquired or results.get(FENCE, {}).get("token") != self._fence:
                raise LeaseLostError("kernel execution incarnation superseded")
            current = decode(results[KEY])
            if (current.revision != state.revision or current.pending != state.pending
                    or current.pending is None or current.terminal is not None):
                raise ConcurrentModificationError("kernel dispatch is not reserved")
            if results[FENCE].get("dispatch") == state.pending.id:
                raise ConcurrentModificationError("kernel dispatch already authorized")
            # This durable receipt precedes external dispatch. A crash now is
            # ambiguous and retains the reservation; it never grants a replay.
            results = dict(results)
            results[FENCE] = {"token": self._fence, "dispatch": state.pending.id}
            row.task_results = results

    def save(self, state, *, expected_revision):
        if state.run_id != self.run_id:
            raise ValueError("kernel run scope mismatch")
        with Session(self.engine) as session, session.begin():
            row = self._row(session)
            results = dict(row.task_results or {})
            if not self._acquired or results.get(FENCE, {}).get("token") != self._fence:
                raise LeaseLostError("kernel execution incarnation superseded")
            old = results.get(KEY)
            actual = old["revision"] if old is not None else -1
            if actual != expected_revision or state.revision != expected_revision + 1:
                raise ConcurrentModificationError("kernel revision mismatch")
            if old is not None and any(old[k] != getattr(state, k) for k in
                                       ("run_id", "method", "input_fingerprint", "limits", "version")):
                raise ValueError("immutable kernel envelope changed")
            if old is not None:
                validate_transition(decode(old), state)
            results[KEY] = encode(state)
            row.task_results = results
