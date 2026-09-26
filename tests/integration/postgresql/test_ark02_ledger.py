"""Real PostgreSQL ledger/checkpoint races on an explicitly disposable database."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from application.execution.exceptions import LeaseLostError
from application.persistence.exceptions import ConcurrentModificationError
from application.research_kernel.controller import Controller
from application.research_kernel.contracts import Stop
from infrastructure.persistence.postgresql.kernel_ownership import KEY, FENCE
from infrastructure.persistence.postgresql.models.project_model import ProjectModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.repositories.postgresql_kernel_state_store import PostgreSQLKernelStateStore
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import create_test_engine, require_integration_tests, reset_schema
from tests.application.test_ark02_kernel import Crash, FakeMethod, state


class PostgreSQLKernelLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_integration_tests()
        cls.engine = create_test_engine()
        cls.addClassCleanup(cls.engine.dispose)

    def setUp(self):
        reset_schema(self.engine)
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            session.add(ProjectModel(id="project", name="Synthetic kernel test", status="created"))
            session.flush()
            session.add(WorkflowRunModel(id="run", project_id="project", workflow_template_id="template",
                status="created", dependency_graph={}, task_results={}, version=0,
                claimed_by="worker", lease_expires_at=now + timedelta(minutes=5), heartbeat_at=now))
        self.repo = PostgreSQLWorkflowRunRepository(DatabaseSessionFactory(self.engine))

    def store(self, **overrides):
        return PostgreSQLKernelStateStore(self.engine, **dict(
            {"run_id": "run", "project_id": "project", "worker_id": "worker"}, **overrides))

    def test_full_controller_durable_restart_does_not_dispatch_again(self):
        method = FakeMethod()
        result = Controller(self.store(), method).run(state())
        restored = Controller(self.store(), method).run(state())
        self.assertEqual(result, restored)
        self.assertEqual(len(method.calls), 8)
        self.assertEqual(restored.used["readings"], 8)

    def test_stale_general_checkpoint_cannot_erase_or_refund_ledger(self):
        aggregate = self.repo.get_by_id("run")
        stale = self.repo.get_task_results("run")
        result = Controller(self.store(), FakeMethod()).run(state())
        durable = self.repo.get_task_results("run")
        stale[KEY] = {"used": {}, "revision": 0}
        stale[FENCE] = "stale-token"
        self.repo.save(aggregate, expected_version=0, task_results=stale)
        after = self.repo.get_task_results("run")
        self.assertEqual(after[KEY], durable[KEY])
        self.assertEqual(after[FENCE], durable[FENCE])
        self.assertEqual(after[KEY]["used"], result.used)

    def test_general_checkpoint_cannot_install_forged_kernel(self):
        self.repo.save(self.repo.get_by_id("run"), expected_version=0,
                       task_results={KEY: {"terminal": "ready"}, FENCE: "forged"})
        self.assertNotIn(KEY, self.repo.get_task_results("run"))

    def test_same_worker_new_incarnation_fences_old_writer(self):
        first, second = self.store(), self.store()
        first.load()
        second.load()
        with self.assertRaises(LeaseLostError):
            first.save(state(), expected_revision=-1)
        second.save(state(), expected_revision=-1)

    def test_revision_cas_prevents_duplicate_initialization(self):
        store = self.store()
        store.load()
        store.save(state(), expected_revision=-1)
        with self.assertRaises(ConcurrentModificationError):
            store.save(state(), expected_revision=-1)

    def test_scope_and_expired_lease_fail_closed(self):
        for overrides in ({"project_id": "foreign"}, {"worker_id": "foreign"}):
            with self.subTest(overrides=overrides), self.assertRaises(LeaseLostError):
                self.store(**overrides).load()
        with Session(self.engine) as session, session.begin():
            session.get(WorkflowRunModel, "run").lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with self.assertRaises(LeaseLostError):
            self.store().load()

    def test_crash_after_provider_retains_reservation_no_replay(self):
        method = FakeMethod()
        method.crash = True
        with self.assertRaises(Crash):
            Controller(self.store(), method).run(state())
        pending = self.repo.get_task_results("run")[KEY]
        aggregate = self.repo.get_by_id("run")
        self.repo.save(aggregate, expected_version=0, task_results={})
        self.assertEqual(self.repo.get_task_results("run")[KEY], pending)
        method.crash = False
        result = Controller(self.store(), method).run(state())
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertEqual(method.calls, ["0"])
        self.assertEqual(result.reservations["0"]["readings"], 1)

    def test_superseded_dispatch_is_rejected_before_provider(self):
        outer = self
        class SupersededStore(PostgreSQLKernelStateStore):
            def authorize_dispatch(self, candidate):
                outer.store().load()
                super().authorize_dispatch(candidate)
        method = FakeMethod()
        store = SupersededStore(self.engine, run_id="run", project_id="project", worker_id="worker")
        with self.assertRaises(LeaseLostError):
            Controller(store, method).run(state())
        self.assertFalse(method.calls)
        recovered = Controller(self.store(), method).run(state())
        self.assertEqual(recovered.terminal, Stop.RECONCILIATION)
        self.assertFalse(method.calls)

    def test_duplicate_dispatch_receipt_rejected(self):
        store, method = self.store(), FakeMethod()
        method.crash = True
        with self.assertRaises(Crash):
            Controller(store, method).run(state())
        pending = store.load()
        with self.assertRaises(ConcurrentModificationError):
            store.authorize_dispatch(pending)
        self.assertEqual(method.calls, ["0"])

    def test_consumed_budget_cannot_be_resurrected_with_fresh_revision(self):
        class InterruptAfterOutcome(PostgreSQLKernelStateStore):
            def save(self, candidate, *, expected_revision):
                super().save(candidate, expected_revision=expected_revision)
                if len(candidate.completed) == 1:
                    raise Crash()
        store = InterruptAfterOutcome(self.engine, run_id="run", project_id="project", worker_id="worker")
        with self.assertRaises(Crash):
            Controller(store, FakeMethod()).run(state())
        persisted = store.load()
        forgery = state()
        forgery.revision = persisted.revision + 1
        with self.assertRaises(ValueError):
            store.save(forgery, expected_revision=persisted.revision)
        self.assertEqual(store.load(), persisted)

    def test_reservation_survives_unrelated_outer_transaction_rollback(self):
        store = self.store()
        with self.assertRaises(RuntimeError):
            with DatabaseSessionFactory(self.engine).transaction():
                store.load()
                store.save(state(), expected_revision=-1)
                raise RuntimeError("outer operation failed")
        self.assertEqual(store.load(), state())

    def test_stale_revision_after_interleaved_outcome_is_rejected(self):
        store = self.store()
        store.load()
        store.save(state(), expected_revision=-1)
        stale = store.load()
        Controller(store, FakeMethod()).run(state())
        stale.revision += 1
        with self.assertRaises(ConcurrentModificationError):
            store.save(stale, expected_revision=0)

    def test_outer_row_lock_fails_closed_without_provider_call(self):
        method = FakeMethod()
        with Session(self.engine) as session, session.begin():
            session.scalar(select(WorkflowRunModel).where(
                WorkflowRunModel.id == "run").with_for_update())
            with self.assertRaises(OperationalError):
                Controller(self.store(), method).run(state())
        self.assertFalse(method.calls)


if __name__ == "__main__":
    unittest.main()
