from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import BadRequestError

from application.execution.execution_budget_context import execution_stage_scope
from application.quantitative.execution_diagnostics import (
    SEMANTIC_LEDGER_KEY,
    _digest,
    semantic_call_recording_scope,
    validate_diagnostics,
)
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from domain.project import Project
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient, model_supports_reasoning
from infrastructure.quantitative.llm_generators import (
    LLMQuantitativeFindingGenerator,
    LLMQuantitativeInsightGenerator,
    LLMQuantitativeReportGenerator,
)
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


def _response():
    return SimpleNamespace(
        status="completed",
        output_text="{}",
        usage=SimpleNamespace(
            output_tokens=1,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        incomplete_details=None,
    )


class _Checkpoint:
    def __init__(self):
        self.snapshots = []

    def on_task_progress(self, context):
        self.snapshots.append(copy.deepcopy(context.shared_state))


class ProviderCapabilityRequestTests(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_gpt_4_1_family_and_unknown_models_omit_reasoning(self, openai_cls):
        api = Mock()
        api.responses.create.return_value = _response()
        openai_cls.return_value = api
        models = (
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4.1-mini-2025-04-14",
            "future-unknown-model",
        )
        for model in models:
            with self.subTest(model=model):
                api.responses.create.reset_mock()
                response = OpenAIClient(
                    LLMConfiguration(model=model, max_tokens=4096)
                ).generate(
                    Prompt(system="System", user="Aggregate payload"),
                    options=LLMGenerationOptions(
                        max_output_tokens=8192,
                        reasoning_effort="minimal",
                    ),
                )
                kwargs = api.responses.create.call_args.kwargs
                self.assertNotIn("reasoning", kwargs)
                self.assertEqual(kwargs["max_output_tokens"], 8192)
                self.assertEqual(kwargs["model"], model)
                self.assertEqual(
                    kwargs["input"],
                    [
                        {"role": "system", "content": "System"},
                        {"role": "user", "content": "Aggregate payload"},
                    ],
                )
                self.assertIsNone(response.configured_reasoning_effort)
                self.assertFalse(model_supports_reasoning(model))

    @patch("openai.OpenAI")
    def test_known_reasoning_model_preserves_reasoning(self, openai_cls):
        api = Mock()
        api.responses.create.return_value = _response()
        openai_cls.return_value = api
        OpenAIClient(LLMConfiguration(model="gpt-5", max_tokens=4096)).generate(
            Prompt(system="System", user="Aggregate payload"),
            options=LLMGenerationOptions(
                max_output_tokens=8192,
                reasoning_effort="minimal",
            ),
        )
        self.assertEqual(
            api.responses.create.call_args.kwargs["reasoning"],
            {"effort": "minimal"},
        )
        self.assertTrue(model_supports_reasoning("o3-mini"))

    @patch("openai.OpenAI")
    def test_quantitative_qi_qj_qk_share_capability_aware_wire_contract(
        self, openai_cls
    ):
        api = Mock()
        api.responses.create.return_value = _response()
        openai_cls.return_value = api
        client = OpenAIClient(
            LLMConfiguration(model="gpt-4.1-mini", max_tokens=4096)
        )
        generators = (
            LLMQuantitativeFindingGenerator,
            LLMQuantitativeInsightGenerator,
            LLMQuantitativeReportGenerator,
        )
        for generator_type in generators:
            with self.subTest(generator=generator_type.__name__):
                api.responses.create.reset_mock()
                generator = generator_type(
                    llm_client=client,
                    json_validator=JsonValidator(),
                    max_output_tokens=8192,
                    reasoning_effort="minimal",
                )
                generator.generate("Aggregate authority")
                kwargs = api.responses.create.call_args.kwargs
                self.assertNotIn("reasoning", kwargs)
                self.assertEqual(kwargs["max_output_tokens"], 8192)
                self.assertEqual(kwargs["input"][1]["content"], "Aggregate authority")


class SafeProviderErrorMetadataTests(unittest.TestCase):
    def _context(self):
        task = make_task("quant_findings", task_id="task")
        run = make_workflow_run(task)
        run.project_id = "project"
        run.ready()
        run.start()
        task.ready()
        task.start()
        return WorkflowContext(
            workflow_run=run,
            project=Project(id="project", name="Project"),
            current_task=task,
            shared_state={"quantitative": {}},
        )

    @patch("openai.OpenAI")
    def test_bad_request_metadata_is_bounded_durable_and_restart_safe(
        self, openai_cls
    ):
        request = httpx.Request("POST", "https://offline.invalid/v1/responses")
        response = httpx.Response(
            400,
            request=request,
            headers={"x-request-id": "req-safe-123"},
        )
        error = BadRequestError(
            "safe summary",
            response=response,
            body={
                "error": {
                    "message": "Unsupported value for reasoning effort",
                    "type": "invalid_request_error",
                    "param": "reasoning.effort",
                    "code": "unsupported_value",
                }
            },
        )
        api = Mock()
        api.responses.create.side_effect = error
        openai_cls.return_value = api
        context = self._context()
        with semantic_call_recording_scope(context, _Checkpoint()):
            with execution_stage_scope("quant_findings"):
                with self.assertRaises(BadRequestError):
                    OpenAIClient(
                        LLMConfiguration(model="gpt-4.1-mini", max_tokens=8192)
                    ).generate(Prompt(system="bounded", user="aggregate only"))
        persisted = {SEMANTIC_LEDGER_KEY: copy.deepcopy(context.shared_state[SEMANTIC_LEDGER_KEY])}
        first = validate_diagnostics(
            persisted, project_id="project", run_id=context.workflow_run.id
        )
        second = validate_diagnostics(
            copy.deepcopy(persisted),
            project_id="project",
            run_id=context.workflow_run.id,
        )
        self.assertEqual(first, second)
        entry = first["calls"][0]
        self.assertEqual(entry["status"], "FAILED_AFTER_DISPATCH")
        self.assertEqual(first["dispatched"]["QI"], 1)
        self.assertEqual(
            entry["provider_error_metadata"],
            {
                "status_code": 400,
                "code": "unsupported_value",
                "type": "invalid_request_error",
                "param": "reasoning.effort",
                "message": "Unsupported value for reasoning effort",
                "request_id": "req-safe-123",
                "exception_class": "BadRequestError",
            },
        )
        encoded = repr(entry).casefold()
        for forbidden in ("authorization", "api key", "prompt", "request body"):
            self.assertNotIn(forbidden, encoded)

    @patch("openai.OpenAI")
    def test_sensitive_provider_message_is_redacted(self, openai_cls):
        request = httpx.Request("POST", "https://offline.invalid/v1/responses")
        response = httpx.Response(400, request=request)
        error = BadRequestError(
            "unsafe",
            response=response,
            body={"error": {"message": "Authorization Bearer sk-secret C:\\Users\\name\\data.sav"}},
        )
        api = Mock()
        api.responses.create.side_effect = error
        openai_cls.return_value = api
        context = self._context()
        with semantic_call_recording_scope(context, _Checkpoint()):
            with execution_stage_scope("quant_findings"):
                with self.assertRaises(BadRequestError):
                    OpenAIClient(
                        LLMConfiguration(model="gpt-4.1-mini", max_tokens=10)
                    ).generate(Prompt(system="bounded", user="aggregate only"))
        entry = context.shared_state[SEMANTIC_LEDGER_KEY][0]
        self.assertEqual(
            entry["provider_error_metadata"]["message"],
            "[redacted provider diagnostic]",
        )
        self.assertNotIn("sk-secret", repr(entry))

    def test_historical_entry_without_provider_metadata_remains_valid(self):
        context = self._context()
        checkpoint = _Checkpoint()
        with semantic_call_recording_scope(context, checkpoint):
            from application.quantitative.execution_diagnostics import (
                get_semantic_call_recorder,
            )
            recorder = get_semantic_call_recorder()
            call_id = recorder.planned(
                stage="QI",
                provider="openai",
                model="gpt-4.1-mini",
                input_fingerprint="f" * 64,
            )
            recorder.dispatched(call_id)
            recorder.failed(call_id, RuntimeError("legacy"), after_dispatch=True)
        historical = copy.deepcopy(context.shared_state[SEMANTIC_LEDGER_KEY])
        historical[0].pop("provider_error_metadata", None)
        historical[0].pop("audit_fingerprint")
        historical[0]["audit_fingerprint"] = _digest(historical[0])
        projection = validate_diagnostics(
            {SEMANTIC_LEDGER_KEY: historical},
            project_id="project",
            run_id=context.workflow_run.id,
        )
        self.assertEqual(projection["calls"][0]["status"], "FAILED_AFTER_DISPATCH")


if __name__ == "__main__":
    unittest.main()
