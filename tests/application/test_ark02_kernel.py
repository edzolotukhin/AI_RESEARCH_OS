"""Offline contract tests; no production provider or database is constructed."""
from copy import deepcopy
import unittest

from application.research_kernel.contracts import (
    Action, Gap, KernelState, Observation, Outcome, OutcomeKind, Stop,
)
from application.research_kernel.controller import Controller
from application.research_kernel.ledger import CapacityError, Ledger


class Crash(BaseException):
    pass


class Store:
    def __init__(self):
        self.state = None
        self.saves = 0
        self.crash_after = None

    def load(self):
        return deepcopy(self.state)

    def authorize_dispatch(self, state):
        if self.state != state or state.pending is None or state.terminal:
            raise RuntimeError("dispatch not reserved")

    def save(self, state, *, expected_revision):
        actual = self.state.revision if self.state else -1
        if actual != expected_revision:
            raise RuntimeError("stale revision")
        self.state = deepcopy(state)
        self.saves += 1
        if self.saves == self.crash_after:
            raise Crash()


class FakeMethod:
    """Non-Desk method: bounded synthetic instrument readings, custom readiness."""
    method_id = "synthetic-instrument-v1"

    def __init__(self, count=8, outcomes=None, sufficient_after=None):
        self.count = count
        self.outcomes = outcomes or {}
        self.sufficient_after = sufficient_after
        self.calls = []
        self.crash = False

    def observe(self, state):
        ready = self.sufficient_after is not None and len(state.completed) >= self.sufficient_after
        return Observation(str(len(state.completed)), (Gap("sample", "uncovered", 1),), ready)

    def propose(self, state, observation):
        return tuple(Action(str(i), "read-instrument", "sample", "sample:"+str(i),
                            "untried_measurement", (("readings", 1),
                            ("initial" if i < 6 else "continuation", 1)), (i,))
                     for i in range(self.count))

    def execute(self, action):
        self.calls.append(action.id)
        if self.crash:
            raise Crash()
        return self.outcomes.get(action.id, Outcome(OutcomeKind.EMPTY))

    def validate(self, action, outcome):
        return outcome


def state():
    return KernelState("run", FakeMethod.method_id, "frozen-input", {
        "decisions": 20, "readings": 8, "initial": 6, "continuation": 2,
    })


class KernelTests(unittest.TestCase):
    def test_six_empty_then_two_reserved_without_fabricated_evidence(self):
        method, store = FakeMethod(), Store()
        result = Controller(store, method).run(state())
        self.assertEqual(method.calls, list(map(str, range(8))))
        self.assertEqual(result.used["initial"], 6)
        self.assertEqual(result.used["continuation"], 2)
        self.assertTrue(all(o.kind == OutcomeKind.EMPTY for o in result.completed.values()))
        self.assertEqual(result.terminal, Stop.OPPORTUNITIES)

    def test_no_ninth_reading(self):
        method = FakeMethod(9)
        result = Controller(Store(), method).run(state())
        self.assertEqual(len(method.calls), 8)
        self.assertEqual(result.terminal, Stop.BUDGET)

    def test_no_opportunity_stops_empty(self):
        self.assertEqual(Controller(Store(), FakeMethod(0)).run(state()).terminal, Stop.OPPORTUNITIES)

    def test_sufficient_stops_without_dispatch(self):
        method = FakeMethod(sufficient_after=0)
        self.assertEqual(Controller(Store(), method).run(state()).terminal, Stop.READY)
        self.assertFalse(method.calls)

    def test_sufficient_after_seventh(self):
        method = FakeMethod(sufficient_after=7)
        self.assertEqual(Controller(Store(), method).run(state()).terminal, Stop.READY)
        self.assertEqual(len(method.calls), 7)

    def test_outcomes_do_not_imply_sufficiency(self):
        for kind in OutcomeKind:
            with self.subTest(kind=kind):
                result = Controller(Store(), FakeMethod(outcomes={"0": Outcome(kind)})).run(state())
                self.assertNotEqual(result.terminal, Stop.READY)
                self.assertEqual(len(result.completed), 8)

    def test_telemetry_on_off_and_broken_are_identical(self):
        outputs = []
        def broken(event):
            raise RuntimeError("observer unavailable")
        for observer in (None, lambda event: None, broken):
            method = FakeMethod()
            outputs.append(Controller(Store(), method, observer).run(state()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_crash_before_initial_persistence_makes_no_call(self):
        store, method = Store(), FakeMethod()
        store.crash_after = 1
        with self.assertRaises(Crash):
            Controller(store, method).run(state())
        self.assertFalse(method.calls)
        store.crash_after = None
        Controller(store, method).run(state())
        self.assertEqual(len(method.calls), 8)

    def test_crash_after_reservation_is_not_replayed(self):
        store, method = Store(), FakeMethod()
        store.crash_after = 2
        with self.assertRaises(Crash):
            Controller(store, method).run(state())
        store.crash_after = None
        result = Controller(store, method).run(state())
        self.assertFalse(method.calls)
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertEqual(Ledger(result).remaining("readings"), 7)

    def test_crash_after_provider_does_not_repeat_or_refund(self):
        store, method = Store(), FakeMethod()
        method.crash = True
        with self.assertRaises(Crash):
            Controller(store, method).run(state())
        method.crash = False
        result = Controller(store, method).run(state())
        self.assertEqual(method.calls, ["0"])
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertEqual(Ledger(result).remaining("readings"), 7)

    def test_crash_after_outcome_resumes_next_action(self):
        store, method = Store(), FakeMethod()
        store.crash_after = 3
        with self.assertRaises(Crash):
            Controller(store, method).run(state())
        store.crash_after = None
        result = Controller(store, method).run(state())
        self.assertEqual(method.calls, list(map(str, range(8))))
        self.assertEqual(result.used["readings"], 8)

    def test_terminal_rerun_has_no_side_effect(self):
        store, method = Store(), FakeMethod()
        controller = Controller(store, method)
        first = controller.run(state())
        self.assertEqual(controller.run(state()), first)
        self.assertEqual(len(method.calls), 8)

    def test_changed_input_or_budget_rejected(self):
        store = Store()
        Controller(store, FakeMethod(0)).run(state())
        for key in ("input_fingerprint", "limits", "version", "run_id"):
            candidate = state()
            setattr(candidate, key, {} if key == "limits" else "changed")
            with self.subTest(key=key), self.assertRaises(ValueError):
                Controller(store, FakeMethod()).run(candidate)

    def test_failed_checkpoint_blocks_dispatch(self):
        class BrokenStore(Store):
            def save(self, state, *, expected_revision):
                if expected_revision >= 0:
                    raise RuntimeError("database unavailable")
                super().save(state, expected_revision=expected_revision)
        method = FakeMethod()
        with self.assertRaises(RuntimeError):
            Controller(BrokenStore(), method).run(state())
        self.assertFalse(method.calls)

    def test_repeated_strategy_does_not_loop(self):
        class Repeating(FakeMethod):
            def propose(self, state, observation):
                return (Action(str(state.revision), "read", "sample", "same", "retry", ()),)
        method = Repeating()
        result = Controller(Store(), method).run(state())
        self.assertEqual(len(method.calls), 1)
        self.assertEqual(result.terminal, Stop.OPPORTUNITIES)

    def test_free_decisions_are_bounded(self):
        class Free(FakeMethod):
            def propose(self, state, observation):
                return (Action(str(state.revision), "read", "sample", str(state.revision), "next", ()),)
        method = Free()
        result = Controller(Store(), method).run(state())
        self.assertEqual(len(method.calls), 20)
        self.assertEqual(result.terminal, Stop.BUDGET)

    def test_negative_duplicate_unknown_resource_rejected(self):
        with self.assertRaises(ValueError):
            Action("a", "read", "n", "s", "r", (("readings", -1),))
        with self.assertRaises(ValueError):
            Action("a", "read", "n", "s", "r", (("readings", 1), ("readings", 1)))
        ledger = Ledger(state())
        with self.assertRaises(CapacityError):
            ledger.reserve(Action("a", "read", "n", "s", "r", (("unbounded", 1),)))

    def test_stale_store_revision_is_rejected(self):
        store = Store()
        store.save(state(), expected_revision=-1)
        with self.assertRaises(RuntimeError):
            store.save(state(), expected_revision=-1)


if __name__ == "__main__":
    unittest.main()
