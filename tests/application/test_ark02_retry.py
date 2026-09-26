"""Actual SDK transport through an in-process HTTP mock; network is never used."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import httpx

from application.research_kernel.contracts import Action, KernelState, Outcome, OutcomeKind, Stop
from application.research_kernel.controller import Controller
from infrastructure.llm.kernel_transport import responses_create
from tests.application.test_ark02_kernel import FakeMethod, Store, Crash


class TransportMethod(FakeMethod):
    def __init__(self, client, swallow=False):
        super().__init__(1)
        self.client, self.swallow = client, swallow

    def propose(self, state, observation):
        return (Action("one", "extract", "need", "one", "test", (("calls", 1), ("retries", 0))),)

    def execute(self, action):
        try:
            responses_create(self.client, {"model": "offline", "input": "synthetic"})
        except Exception:
            if not self.swallow:
                raise
        return Outcome(OutcomeKind.EMPTY)


def initial(limit=3):
    return KernelState("run", FakeMethod.method_id, "frozen", {"decisions": 4, "calls": limit, "retries": 2})


class RetryTests(unittest.TestCase):
    def client(self, handler, retries=2):
        # The import-safety suite intentionally unloads all openai modules.
        # Resolve the SDK here, not at discovery, so exception classes match.
        from openai import OpenAI
        client = OpenAI(api_key="synthetic-offline-secret", max_retries=retries,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(client.close)
        return client

    def run_method(self, handler, limit=3, swallow=False):
        store = Store()
        method = TransportMethod(self.client(handler), swallow)
        with patch("infrastructure.llm.kernel_transport.time.sleep"):
            result = Controller(store, method).run(initial(limit))
        return result, store, method

    def test_sdk_retry_has_precommitted_attempt_reservation_and_safe_terminal_outcome(self):
        snapshots = []
        store = Store()
        def handler(request):
            snapshots.append(deepcopy(store.state))
            if len(snapshots) == 1:
                return httpx.Response(429, json={"error": {"message": "synthetic"}})
            return httpx.Response(200, json={"id": "offline", "output": []})
        method = TransportMethod(self.client(handler))
        with patch("infrastructure.llm.kernel_transport.time.sleep"):
            result = Controller(store, method).run(initial())
        self.assertEqual(len(snapshots), 2)
        for ordinal, snapshot in enumerate(snapshots, 1):
            self.assertEqual(snapshot.reservations["one"]["calls"], ordinal)
            self.assertEqual(snapshot.decisions[0]["attempts"][-1]["ordinal"], ordinal)
            self.assertEqual(snapshot.decisions[0]["attempts"][-1]["outcome"], "ambiguous")
        self.assertEqual(result.used["calls"], 2)
        self.assertEqual(result.used["retries"], 1)
        self.assertEqual([a["outcome"] for a in result.decisions[0]["attempts"]], ["failed", "returned"])
        self.assertNotIn("synthetic-offline-secret", repr(result))
        self.assertNotIn("Authorization", repr(result))

    def test_retry_cannot_exceed_shared_capacity(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(429, json={"error": {"message": "synthetic"}})
        result, _, _ = self.run_method(handler, limit=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.terminal, Stop.BUDGET)
        self.assertEqual(result.used["calls"], 1)

    def test_existing_sdk_retry_ceiling_not_increased(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(429, json={"error": {"message": "synthetic"}})
        result, store, method = self.run_method(handler)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        Controller(store, method).run(initial())
        self.assertEqual(len(calls), 3)
        self.assertEqual(result.reservations["one"]["calls"], 3)

    def test_ambiguous_timeout_is_never_retried_even_if_extractor_swallows(self):
        calls = []
        def handler(request):
            calls.append(1)
            raise httpx.ReadTimeout("synthetic", request=request)
        result, store, method = self.run_method(handler, swallow=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertEqual(result.decisions[0]["attempts"][0]["outcome"], "ambiguous")
        Controller(store, method).run(initial())
        self.assertEqual(len(calls), 1)

    def test_worker_crash_after_provider_cannot_buy_new_capacity(self):
        calls = []
        def handler(request):
            calls.append(1)
            raise Crash()
        store = Store()
        method = TransportMethod(self.client(handler))
        with self.assertRaises(Crash):
            Controller(store, method).run(initial())
        result = Controller(store, method).run(initial())
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.terminal, Stop.RECONCILIATION)
        self.assertEqual(result.reservations["one"]["calls"], 1)

    def test_nonretryable_status_and_retry_header_are_respected(self):
        for status, headers in ((400, {}), (503, {"x-should-retry": "false"})):
            calls = []
            def handler(request):
                calls.append(1)
                return httpx.Response(status, headers=headers, json={"error": {"message": "synthetic"}})
            result, _, _ = self.run_method(handler)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.terminal, Stop.RECONCILIATION)


if __name__ == "__main__":
    unittest.main()
