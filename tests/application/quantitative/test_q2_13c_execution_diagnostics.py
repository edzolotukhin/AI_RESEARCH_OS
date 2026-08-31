from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock

from application.config import ApplicationConfig
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    execution_budget_scope,
    execution_stage_scope,
)
from application.llm.stage_llm_clients import (
    create_quantitative_live_llm_client,
    unwrap_llm_client,
)
from application.quantitative.execution_diagnostics import (
    FAILURE_DIAGNOSTIC_KEY,
    SEMANTIC_LEDGER_KEY,
    QuantitativeExecutionDiagnosticsError,
    build_stage_failure_diagnostic,
    semantic_call_recording_scope,
    validate_diagnostics,
)
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.project import Project
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.llm.llm_client import LLMClient
from infrastructure.llm.llm_configuration import LLMConfiguration
from infrastructure.llm.openai_client import OpenAIClient
from infrastructure.llm.semantic_call_audited_client import SemanticCallAuditedClient
from runtime.workflow_context import WorkflowContext
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class _Checkpoint:
    def __init__(self): self.snapshots = []
    def on_task_progress(self, context): self.snapshots.append(copy.deepcopy(context.shared_state))


class _Client(LLMClient):
    def __init__(self, *, fail=False): self.fail = fail; self.calls = 0
    def generate(self, prompt, *, options=None):
        self.calls += 1
        if self.fail: raise RuntimeError("provider transport detail must not persist")
        return LLMResponse(content='{"proposals":[]}', output_tokens=1)


class _SafetyWrapper(LLMClient):
    def __init__(self, inner): self.inner = inner
    def generate(self, prompt, *, options=None):
        return self.inner.generate(prompt, options=options)


class Q213CExecutionDiagnosticsTests(unittest.TestCase):
    def context(self, definition_id="quant_findings"):
        task = make_task(definition_id, task_id="task")
        run = make_workflow_run(task); run.project_id = "project"; run.ready(); run.start()
        task.ready(); task.start()
        return WorkflowContext(workflow_run=run, project=Project(id="project", name="Project"), current_task=task, shared_state={"quantitative":{"analysis_execution_manifest_record_id":"rd-record"}})

    def call(self, context, definition_id, client, *, accept=True):
        context.current_task.definition_id = definition_id
        stage = {"quant_findings":"quant_findings", "quant_insights":"quant_insights", "quant_report":"quant_report"}[definition_id]
        with semantic_call_recording_scope(context, _Checkpoint()):
            with execution_stage_scope(stage):
                response = SemanticCallAuditedClient(client).generate(Prompt(system="bounded", user="aggregate only"))
                from application.quantitative.execution_diagnostics import get_semantic_call_recorder
                recorder = get_semantic_call_recorder()
                if accept: recorder.complete_current()
                else: recorder.fail_current_after_return(ValueError("decode failure"))
                return response

    def projection(self, context, failure=None):
        results = {SEMANTIC_LEDGER_KEY: context.shared_state.get(SEMANTIC_LEDGER_KEY, ())}
        if failure is not None: results[FAILURE_DIAGNOSTIC_KEY] = failure
        return validate_diagnostics(results, project_id="project", run_id=context.workflow_run.id)

    def test_rd_failure_has_zero_calls_and_bounded_durable_diagnostic(self):
        context = self.context("quant_analysis")
        diagnostic = build_stage_failure_diagnostic(context, RuntimeError("C:\\private\\dataset.sav secret"))
        projection = self.projection(context, diagnostic)
        self.assertEqual(projection["failure"]["stage"], "RD")
        self.assertEqual(projection["total_dispatched"], 0)
        self.assertEqual(projection["failure"]["last_successful_authority"]["record_id"], "rd-record")
        self.assertNotIn("private", repr(projection).casefold())

    def test_qi_local_pre_dispatch_failure_has_zero_calls(self):
        context = self.context()
        diagnostic = build_stage_failure_diagnostic(context, ValueError("local validation"))
        projection = self.projection(context, diagnostic)
        self.assertEqual(projection["dispatched"], {"QI":0,"QJ":0,"QK":0})
        self.assertEqual(projection["failure"]["stage"], "QI")

    def test_qi_post_dispatch_failure_consumes_one_and_is_durable(self):
        context = self.context(); client = _Client(fail=True)
        with self.assertRaises(RuntimeError): self.call(context, "quant_findings", client)
        projection = self.projection(context, build_stage_failure_diagnostic(context, RuntimeError("stage failed")))
        self.assertEqual(projection["dispatched"]["QI"], 1)
        self.assertEqual(projection["remaining"]["QI"], 0)
        self.assertEqual(projection["calls"][0]["status"], "FAILED_AFTER_DISPATCH")

    def test_decode_failure_is_after_dispatch_not_completed(self):
        context = self.context(); self.call(context, "quant_findings", _Client(), accept=False)
        projection = self.projection(context)
        self.assertEqual(projection["calls"][0]["status"], "FAILED_AFTER_DISPATCH")
        self.assertTrue(projection["calls"][0]["returned"])

    def test_qj_and_qk_accounting_is_stage_specific(self):
        context = self.context()
        self.call(context, "quant_findings", _Client())
        with self.assertRaises(RuntimeError): self.call(context, "quant_insights", _Client(fail=True))
        projection = self.projection(context)
        self.assertEqual(projection["dispatched"], {"QI":1,"QJ":1,"QK":0})

        other = self.context(); self.call(other, "quant_findings", _Client()); self.call(other, "quant_insights", _Client())
        with self.assertRaises(RuntimeError): self.call(other, "quant_report", _Client(fail=True))
        self.assertEqual(self.projection(other)["dispatched"], {"QI":1,"QJ":1,"QK":1})

    def test_full_success_restart_projection_and_no_duplicate_budget(self):
        context = self.context()
        for definition in ("quant_findings", "quant_insights", "quant_report"):
            self.call(context, definition, _Client())
        persisted = {SEMANTIC_LEDGER_KEY: copy.deepcopy(context.shared_state[SEMANTIC_LEDGER_KEY])}
        first = validate_diagnostics(persisted, project_id="project", run_id=context.workflow_run.id)
        second = validate_diagnostics(copy.deepcopy(persisted), project_id="project", run_id=context.workflow_run.id)
        self.assertEqual(first, second)
        self.assertEqual(first["dispatched"], {"QI":1,"QJ":1,"QK":1})
        with self.assertRaises(QuantitativeExecutionDiagnosticsError): self.call(context, "quant_report", _Client())

    def test_corruption_wrong_scope_impossible_transition_and_payload_safety(self):
        context = self.context(); self.call(context, "quant_findings", _Client())
        persisted = {SEMANTIC_LEDGER_KEY: copy.deepcopy(context.shared_state[SEMANTIC_LEDGER_KEY])}
        corrupt = copy.deepcopy(persisted); corrupt[SEMANTIC_LEDGER_KEY][0]["provider"] = "changed"
        with self.assertRaises(QuantitativeExecutionDiagnosticsError): validate_diagnostics(corrupt, project_id="project", run_id=context.workflow_run.id)
        with self.assertRaises(QuantitativeExecutionDiagnosticsError): validate_diagnostics(persisted, project_id="wrong", run_id=context.workflow_run.id)
        impossible = copy.deepcopy(persisted)
        impossible[SEMANTIC_LEDGER_KEY][0]["status"] = "COMPLETED"
        impossible[SEMANTIC_LEDGER_KEY][0]["dispatched"] = False
        impossible[SEMANTIC_LEDGER_KEY][0].pop("audit_fingerprint")
        from application.quantitative.execution_diagnostics import _digest
        impossible[SEMANTIC_LEDGER_KEY][0]["audit_fingerprint"] = _digest(impossible[SEMANTIC_LEDGER_KEY][0])
        with self.assertRaises(QuantitativeExecutionDiagnosticsError): validate_diagnostics(impossible, project_id="project", run_id=context.workflow_run.id)
        encoded = repr(persisted).casefold()
        for forbidden in ("prompt", "response prose", "respondent", "raw sav", "api key", "authorization"):
            self.assertNotIn(forbidden, encoded)

    def test_failed_task_persister_saves_failure_and_ledger_for_restart(self):
        context = self.context("quant_analysis"); context.current_task.fail()
        service = Mock(); service.save_workflow_run.return_value = 1
        persister = WorkflowRuntimePersister(workflow_service=service, audit=None, run_id=context.workflow_run.id)
        persister.on_task_finished(context, error=RuntimeError("local path C:\\secret"))
        saved = service.save_workflow_run.call_args.kwargs["task_results"]
        projection = validate_diagnostics(saved, project_id="project", run_id=context.workflow_run.id)
        self.assertEqual(projection["failure"]["stage"], "RD")
        self.assertFalse(projection["terminal_result_persisted"])

    def test_usage_and_semantic_ledger_agree_for_success_failure_and_restart(self):
        for fail, expected_status in ((False, "COMPLETED"), (True, "FAILED_AFTER_DISPATCH")):
            with self.subTest(fail=fail):
                context = self.context()
                budget = ExecutionBudget()
                client = SemanticCallAuditedClient(
                    BudgetEnforcingLLMClient(_Client(fail=fail))
                )
                checkpoint = _Checkpoint()
                with semantic_call_recording_scope(context, checkpoint):
                    with execution_stage_scope("quant_findings"), execution_budget_scope(budget):
                        if fail:
                            with self.assertRaises(RuntimeError):
                                client.generate(Prompt(system="bounded", user="aggregate only"))
                        else:
                            client.generate(Prompt(system="bounded", user="aggregate only"))
                            from application.quantitative.execution_diagnostics import get_semantic_call_recorder
                            get_semantic_call_recorder().complete_current()
                persisted = {
                    SEMANTIC_LEDGER_KEY: copy.deepcopy(context.shared_state[SEMANTIC_LEDGER_KEY]),
                    "_run_usage_summary": budget.summary(),
                }
                first = validate_diagnostics(
                    persisted, project_id="project", run_id=context.workflow_run.id
                )
                second = validate_diagnostics(
                    copy.deepcopy(persisted),
                    project_id="project",
                    run_id=context.workflow_run.id,
                )
                self.assertEqual(first, second)
                self.assertEqual(1, first["dispatched"]["QI"])
                self.assertEqual(expected_status, first["calls"][0]["status"])
                self.assertEqual(
                    1, persisted["_run_usage_summary"]["stages"]["quant_findings"]["llm_calls"]
                )

    def test_usage_ledger_disagreement_fails_closed(self):
        context = self.context()
        persisted = {
            SEMANTIC_LEDGER_KEY: (),
            "_run_usage_summary": {
                "stages": {"quant_findings": {"llm_calls": 1}}
            },
        }
        with self.assertRaisesRegex(
            QuantitativeExecutionDiagnosticsError, "usage and lifecycle ledger disagree"
        ):
            validate_diagnostics(
                persisted, project_id="project", run_id=context.workflow_run.id
            )

    def test_openai_nested_in_safety_wrapper_is_not_double_audited(self):
        live = OpenAIClient(LLMConfiguration(model="offline-test", max_tokens=10))
        safety = _SafetyWrapper(live)
        composed = create_quantitative_live_llm_client(ApplicationConfig(), safety)
        self.assertIs(unwrap_llm_client(composed), safety)


if __name__ == "__main__": unittest.main()
