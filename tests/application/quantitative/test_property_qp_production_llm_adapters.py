from __future__ import annotations

import inspect
import json
import tempfile
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import execution_budget_scope
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import QuantitativeInsightSynthesisService, QuantitativeInsightValidator
from application.quantitative.report_composition import QuantitativeReportCompositionService, QuantitativeReportValidator
from application.quantitative.ui_service import QuantitativeUiService
from application.structured_output.json_validator import JsonValidator
from domain.ai.llm_response import LLMResponse
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.llm.llm_client import LLMClient
from application.llm.stage_llm_clients import create_quantitative_live_llm_client, unwrap_llm_client
from application.quantitative.offline_generators import OfflineFindingGenerator
from infrastructure.quantitative.llm_generators import (
    LLMQuantitativeFindingGenerator,
    LLMQuantitativeInsightGenerator,
    LLMQuantitativeReportGenerator,
    QuantitativeGenerationError,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qi_llm_assisted_finding_generation import proposal
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import result
from tests.application.quantitative.test_property_qj_quantitative_insight_synthesis import insight_proposal
from tests.application.quantitative.test_property_qk_quantitative_report_composition import PropertyQKQuantitativeReportCompositionTests


class RecordingLLMClient(LLMClient):
    def __init__(self, *responses: str, failure: Exception | None = None):
        self.responses = list(responses)
        self.failure = failure
        self.calls = []

    def generate(self, prompt, *, options=None):
        self.calls.append((prompt, options))
        if self.failure is not None:
            raise self.failure
        if not self.responses:
            raise AssertionError("unexpected provider call")
        return LLMResponse(content=self.responses.pop(0), output_tokens=7)


def adapter(kind, client):
    cls = {
        "quant_findings": LLMQuantitativeFindingGenerator,
        "quant_insights": LLMQuantitativeInsightGenerator,
        "quant_report": LLMQuantitativeReportGenerator,
    }[kind]
    return cls(
        llm_client=client,
        json_validator=JsonValidator(),
        max_output_tokens=512,
        reasoning_effort="minimal",
    )


class PropertyQPProductionLlmAdapterTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()

    def test_valid_qi_qj_qk_chain_uses_exactly_three_calls(self):
        authority = result("share", "42")
        qi_payload = {"proposals": [proposal(authority, "DESCRIPTIVE_VALUE")]}
        client = RecordingLLMClient(json.dumps(qi_payload))
        budgeted = BudgetEnforcingLLMClient(client)
        qi = QuantitativeFindingGenerationService(
            generator=adapter("quant_findings", budgeted),
            support_validator=QuantitativeFindingSupportValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        ).generate(statistical_results=(authority,))
        finding = qi.accepted_findings[0]

        client.responses.append(json.dumps({"proposals": [insight_proposal(
            "SYNTHESIS", "The accepted share was 42.0%.", (finding,),
            values=("42.0",),
            fingerprints={finding.finding_id: finding.support_validation_fingerprint},
        )]}))
        qj = QuantitativeInsightSynthesisService(
            generator=adapter("quant_insights", budgeted),
            validator=QuantitativeInsightValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        ).generate(findings=(finding,))
        insight = qj.accepted_insights[0]

        helper = PropertyQKQuantitativeReportCompositionTests()
        helper.setUp()
        report_payload = helper.proposal(finding, insight=insight)
        client.responses.append(json.dumps(report_payload))
        qk = QuantitativeReportCompositionService(
            generator=adapter("quant_report", budgeted),
            validator=QuantitativeReportValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        ).compose(findings=(finding,), insights=(insight,))
        self.assertIsNotNone(qk.accepted_report)
        self.assertEqual(len(client.calls), 3)

    def test_malformed_and_non_object_json_fail_after_one_call_without_repair(self):
        for stage in ("quant_findings", "quant_insights", "quant_report"):
            for response in ("{", "[]"):
                with self.subTest(stage=stage, response=response):
                    client = RecordingLLMClient(response)
                    with self.assertRaises(QuantitativeGenerationError):
                        adapter(stage, client).generate("bounded aggregate prompt")
                    self.assertEqual(len(client.calls), 1)

    def test_provider_failure_is_sanitized_and_not_retried(self):
        client = RecordingLLMClient(failure=TimeoutError("secret provider detail"))
        with self.assertRaisesRegex(QuantitativeGenerationError, "provider generation failed") as raised:
            adapter("quant_findings", client).generate("safe aggregate")
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(client.calls), 1)

    def test_budget_exhaustion_blocks_provider_and_caps_each_stage_independently(self):
        blocked = RecordingLLMClient("{}")
        budget = ExecutionBudget(quant_findings_max_llm_calls=0)
        with execution_budget_scope(budget):
            with self.assertRaises(BudgetExhaustedError):
                adapter("quant_findings", BudgetEnforcingLLMClient(blocked)).generate("safe")
        self.assertEqual(blocked.calls, [])

        client = RecordingLLMClient("{}", "{}", "{}", "{}")
        wrapped = BudgetEnforcingLLMClient(client)
        budget = ExecutionBudget()
        with execution_budget_scope(budget):
            adapter("quant_findings", wrapped).generate("safe")
            with self.assertRaises(BudgetExhaustedError):
                adapter("quant_findings", wrapped).generate("safe")
            adapter("quant_insights", wrapped).generate("safe")
            adapter("quant_report", wrapped).generate("safe")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(budget.stage_calls("quant_findings"), 1)
        self.assertEqual(budget.stage_calls("quant_insights"), 1)
        self.assertEqual(budget.stage_calls("quant_report"), 1)
        self.assertEqual(budget.summary()["total_llm_calls"], 3)
        self.assertEqual(
            set(budget.summary()["stages"]),
            {"quant_findings", "quant_insights", "quant_report"},
        )
        for field in (
            "quant_findings_max_llm_calls",
            "quant_insights_max_llm_calls",
            "quant_report_max_llm_calls",
        ):
            with self.assertRaises(ValueError):
                ExecutionBudget(**{field: 2})

    def test_valid_but_invented_proposal_is_auditable_authority_rejection(self):
        authority = result("share", "42")
        payload = {"proposals": [proposal(
            authority, "DESCRIPTIVE_VALUE", value="999", display="999.0"
        )]}
        client = RecordingLLMClient(json.dumps(payload))
        generated = QuantitativeFindingGenerationService(
            generator=adapter("quant_findings", client),
            support_validator=QuantitativeFindingSupportValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        ).generate(statistical_results=(authority,))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(generated.accepted_findings), 0)
        self.assertEqual(len(generated.rejected_findings), 1)
        self.assertIn("999", str(generated.rejected_findings[0].proposal_payload))

    def test_adapters_have_no_dataset_or_storage_capability(self):
        signature = inspect.signature(LLMQuantitativeFindingGenerator)
        self.assertEqual(
            set(signature.parameters),
            {"llm_client", "json_validator", "max_output_tokens", "reasoning_effort"},
        )
        source = inspect.getsource(__import__(
            "infrastructure.quantitative.llm_generators", fromlist=["*"]
        ))
        for forbidden in (
            "DatasetStorage", "respondent", "pseudonym", "SavPyreadstatAdapter",
            "QualityControl", "protected_file", "domain.evidence",
        ):
            self.assertNotIn(forbidden, source)

    def test_offline_and_production_composition_are_explicit(self):
        fake = RecordingLLMClient("{}")
        with tempfile.TemporaryDirectory() as root:
            offline = create_application_container(
                config=ApplicationConfig(
                    projects_root=root,
                    persistence_backend="memory",
                    background_execution_mode="embedded",
                    deterministic_stage_executors=True,
                    search_provider="deterministic",
                ),
                overrides=ApplicationOverrides(quantitative_llm_client=fake),
            )
            self.assertEqual(offline.quantitative_ui_service.generation_mode, "offline")
            self.assertIsInstance(offline.quantitative_ui_service.finding_generator, OfflineFindingGenerator)
            self.assertEqual(fake.calls, [])
            offline.shutdown()

        fake = RecordingLLMClient("{}")
        with tempfile.TemporaryDirectory() as root:
            production = create_application_container(
                config=ApplicationConfig(
                    projects_root=root,
                    persistence_backend="memory",
                    background_execution_mode="embedded",
                    deterministic_stage_executors=False,
                    search_provider="deterministic",
                ),
                overrides=ApplicationOverrides(quantitative_llm_client=fake),
            )
            self.assertEqual(production.quantitative_ui_service.generation_mode, "production")
            self.assertIsInstance(
                production.quantitative_ui_service.finding_generator,
                LLMQuantitativeFindingGenerator,
            )
            self.assertEqual(fake.calls, [])
            production.shutdown()

    def test_missing_generator_composition_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "generators are not configured"):
            QuantitativeUiService(
                project_service=None,
                workflow_service=None,
                state_service=None,
                digest_provider=None,
                storage_factory=None,
                importers=(),
                finding_generator=None,
                insight_generator=None,
                report_generator=None,
                generation_mode="production",
            )

    def test_live_quantitative_client_disables_sdk_retries_and_bounds_timeout(self):
        config = ApplicationConfig(
            quantitative_llm_timeout_seconds=17.0,
            quantitative_max_output_tokens=321,
        )
        inner = unwrap_llm_client(create_quantitative_live_llm_client(config))
        self.assertEqual(inner._max_retries, 0)
        self.assertEqual(inner._timeout_seconds, 17.0)
        self.assertEqual(inner._configuration.max_tokens, 321)


if __name__ == "__main__":
    unittest.main()
