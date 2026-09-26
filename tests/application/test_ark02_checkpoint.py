"""Persisted-state and real PRF-08S bridge tests, with no external services."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from application import research_funnel_telemetry as funnel
from application.research_kernel.codec import decode, encode
from application.research_kernel.controller import Controller
from application.research_kernel.contracts import Stop
from application.research_kernel.telemetry import observe_decision
from tests.application.test_ark02_kernel import Crash, FakeMethod, Store, state


class CheckpointTests(unittest.TestCase):
    def pending(self):
        store = Store()
        store.crash_after = 2
        with self.assertRaises(Crash):
            Controller(store, FakeMethod()).run(state())
        return store.state

    def test_json_roundtrip_pending_preserves_uncertain_capacity(self):
        original = self.pending()
        restored = decode(json.loads(json.dumps(encode(original))))
        self.assertEqual(restored.pending, original.pending)
        self.assertEqual(restored.reservations, original.reservations)
        store, method = Store(), FakeMethod()
        store.state = restored
        result = Controller(store, method).run(state())
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertFalse(method.calls)

    def test_json_roundtrip_terminal_has_no_new_call(self):
        store, method = Store(), FakeMethod()
        result = Controller(store, method).run(state())
        store.state = decode(json.loads(json.dumps(encode(result))))
        self.assertEqual(Controller(store, method).run(state()).used, result.used)
        self.assertEqual(len(method.calls), 8)

    def test_corrupt_reserved_amount_rejected_before_recovery(self):
        payload = encode(self.pending())
        payload["reservations"]["0"]["readings"] = 0
        with self.assertRaises(ValueError):
            decode(payload)

    def test_orphan_reservation_rejected(self):
        payload = encode(state())
        payload["reservations"]["orphan"] = {"readings": 1}
        with self.assertRaises(ValueError):
            decode(payload)

    def test_unknown_version_stop_and_outcome_fail_closed(self):
        result = Controller(Store(), FakeMethod()).run(state())
        for field in ("version", "terminal", "outcome"):
            payload = encode(result)
            if field == "outcome":
                payload["completed"]["0"]["kind"] = "future-outcome"
            else:
                payload[field] = "future"
            with self.subTest(field=field), self.assertRaises(ValueError):
                decode(payload)

    def test_completed_accounting_cannot_be_refunded(self):
        payload = encode(Controller(Store(), FakeMethod()).run(state()))
        payload["used"]["decisions"] = 0
        with self.assertRaises(ValueError):
            decode(payload)

    def test_non_pristine_initial_state_is_rejected(self):
        candidate = state()
        candidate.used["readings"] = 1
        method = FakeMethod()
        with self.assertRaises(ValueError):
            Controller(Store(), method).run(candidate)
        self.assertFalse(method.calls)

    def test_invalid_stored_checkpoint_blocks_even_terminal_return(self):
        store, method = Store(), FakeMethod()
        Controller(store, method).run(state())
        store.state.used["readings"] = 9
        with self.assertRaises(ValueError):
            Controller(store, method).run(state())
        self.assertEqual(len(method.calls), 8)


class TelemetryTests(unittest.TestCase):
    class Driver:
        @funnel.observed("adaptive_kernel")
        def run(self, context):
            return Controller(Store(), FakeMethod(), observe_decision).run(state())

    def context(self, enabled=True):
        return SimpleNamespace(execution_metadata={"research_funnel_enabled": enabled},
                               shared_state={}, workflow_run=SimpleNamespace(id="synthetic-run"))

    def test_actual_journal_enabled_disabled_capped_identical(self):
        enabled, disabled, capped = self.context(), self.context(False), self.context()
        first = self.Driver().run(enabled)
        second = self.Driver().run(disabled)
        with patch.object(funnel, "MAX_EVENTS", 1):
            third = self.Driver().run(capped)
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertNotIn(funnel.KEY, disabled.shared_state)
        self.assertEqual(len(capped.shared_state[funnel.KEY]["events"]), 1)
        self.assertGreater(capped.shared_state[funnel.KEY]["dropped_events"], 0)
        self.assertEqual(len(enabled.shared_state[funnel.KEY]["events"]), 17)

    def test_bridge_does_not_emit_unknown_fields_or_credentials(self):
        context = self.context()
        class Emitter:
            @funnel.observed("adaptive_kernel")
            def run(self, context):
                observe_decision({"action": "action-1", "reason": "Bearer synthetic-secret",
                                  "provider_body": "never-persist-this", "authorization": "private"})
        Emitter().run(context)
        text = json.dumps(context.shared_state)
        for forbidden in ("synthetic-secret", "never-persist-this", "private", "provider_body"):
            self.assertNotIn(forbidden, text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
