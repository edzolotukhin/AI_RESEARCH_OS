import unittest

from application.report.h3_provider_contract import (
    H3ProviderBudget,
    H3ProviderBudgetExceeded,
    debit_h3_provider_call,
    h3_provider_budget,
)
from infrastructure.report.h3_llm_providers import LlmH3EditorialProvider
from infrastructure.review.h3_llm_provider import LlmH3ReviewProvider


class _Response:
    content = '{"ok": true}'


class _Client:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return _Response()


class H3ProviderContractTests(unittest.TestCase):
    def test_budget_rejects_call_eight_before_dispatch(self):
        budget = H3ProviderBudget(limit=7)
        calls = []
        with h3_provider_budget(budget):
            for _ in range(7):
                debit_h3_provider_call()
            with self.assertRaises(H3ProviderBudgetExceeded):
                debit_h3_provider_call()
            calls.append(budget.used)
        self.assertEqual([7], calls)

    def test_production_adapters_are_explicit_typed_boundaries(self):
        client = _Client()
        editorial = LlmH3EditorialProvider(client)
        review = LlmH3ReviewProvider(client)
        self.assertEqual({"ok": True}, editorial.compose({}))
        self.assertEqual({"ok": True}, review.review({}))
        self.assertEqual(2, client.calls)


if __name__ == "__main__":
    unittest.main()
