from __future__ import annotations

import unittest

from application.quantitative.execution_diagnostics import (
    SEMANTIC_LEDGER_KEY,
    semantic_call_recording_scope,
    validate_diagnostics,
)
from application.structured_output.json_validator import JsonValidator
from domain.ai.llm_response import LLMResponse
from domain.project import Project
from infrastructure.llm.llm_client import LLMClient
from infrastructure.llm.semantic_call_audited_client import SemanticCallAuditedClient
from infrastructure.quantitative.llm_generators import (
    LLMQuantitativeFindingGenerator,
    QuantitativeGenerationError,
)
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_workflow_run


class _ResponseClient(LLMClient):
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def generate(self, prompt, *, options=None):
        self.calls += 1
        return LLMResponse(content=self.content)


def _context():
    run = make_workflow_run(run_id="qi-structured-diagnostic-run")
    return WorkflowContext(
        workflow_run=run,
        project=Project(id="qi-structured-diagnostic-project", name="QI diagnostics"),
        current_task=type("Task", (), {"definition_id": "quant_findings"})(),
        shared_state={},
    )


class Q213AStructuredGenerationDiagnosticsTests(unittest.TestCase):
    def _generator(self, content: str):
        client = _ResponseClient(content)
        return (
            LLMQuantitativeFindingGenerator(
                llm_client=SemanticCallAuditedClient(client),
                json_validator=JsonValidator(),
                max_output_tokens=128,
            ),
            client,
        )

    def test_contract_valid_object_succeeds_and_completes_single_call(self):
        context = _context()
        generator, client = self._generator('{"proposals":[]}')
        with semantic_call_recording_scope(context, None):
            self.assertEqual({"proposals": []}, generator.generate("bounded aggregate authority"))
        self.assertEqual(1, client.calls)
        self.assertEqual("COMPLETED", context.shared_state[SEMANTIC_LEDGER_KEY][0]["status"])

    def test_invalid_json_fails_closed_with_safe_persistable_parse_classification(self):
        context = _context()
        generator, client = self._generator("{")
        with semantic_call_recording_scope(context, None):
            with self.assertRaisesRegex(QuantitativeGenerationError, "malformed") as raised:
                generator.generate("bounded aggregate authority")
        self.assertEqual("INVALID_JSON", raised.exception.structured_failure_code)
        entry = context.shared_state[SEMANTIC_LEDGER_KEY][0]
        self.assertEqual("FAILED_AFTER_DISPATCH", entry["status"])
        self.assertEqual("INVALID_JSON", entry["structured_failure"]["code"])
        self.assertNotIn("response", entry["structured_failure"])
        self.assertEqual(1, client.calls)
        self.assertEqual(
            1,
            validate_diagnostics(
                {SEMANTIC_LEDGER_KEY: context.shared_state[SEMANTIC_LEDGER_KEY]},
                project_id=context.project.id,
                run_id=context.workflow_run.id,
            )["total_dispatched"],
        )

    def test_json_non_object_remains_fail_closed_with_distinct_safe_classification(self):
        context = _context()
        generator, _ = self._generator("[]")
        with semantic_call_recording_scope(context, None):
            with self.assertRaisesRegex(QuantitativeGenerationError, "must be an object") as raised:
                generator.generate("bounded aggregate authority")
        self.assertEqual("TOP_LEVEL_NOT_OBJECT", raised.exception.structured_failure_code)
        self.assertEqual(
            "TOP_LEVEL_NOT_OBJECT",
            context.shared_state[SEMANTIC_LEDGER_KEY][0]["structured_failure"]["code"],
        )


if __name__ == "__main__":
    unittest.main()