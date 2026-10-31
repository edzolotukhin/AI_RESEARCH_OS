import os
import unittest
from unittest import mock

from application.report.h3_provider_smoke import H3ProviderSmokeDisabled, validate_h3_provider_smoke
from application.report.typed_rendering import H3_CONTRACT_VERSION


class H3ProviderSmokeTests(unittest.TestCase):
    def test_smoke_requires_explicit_enable_and_does_not_call_provider(self):
        calls = []
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_RESEARCH_ENABLE_H3_PROVIDER_SMOKE", None)
            with self.assertRaises(H3ProviderSmokeDisabled):
                validate_h3_provider_smoke(
                    provider=lambda request: calls.append(request),
                    request={"contract_version": H3_CONTRACT_VERSION, "claims": []},
                )
        self.assertEqual(calls, [])

    def test_enabled_smoke_calls_once_and_discards_response(self):
        calls = []
        with mock.patch.dict(os.environ, {"AI_RESEARCH_ENABLE_H3_PROVIDER_SMOKE": "1"}):
            result = validate_h3_provider_smoke(
                provider=lambda request: (calls.append(request) or {
                    "contract_version": H3_CONTRACT_VERSION, "claims": [],
                }),
                request={"contract_version": H3_CONTRACT_VERSION, "claims": []},
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["provider_calls"], 1)
        self.assertEqual(result["validated_claim_ids"], [])
