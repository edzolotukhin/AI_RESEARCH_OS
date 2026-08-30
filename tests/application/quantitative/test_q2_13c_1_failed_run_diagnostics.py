from __future__ import annotations

import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from application.quantitative.execution_diagnostics import (
    FAILURE_DIAGNOSTIC_KEY,
    SEMANTIC_LEDGER_KEY,
    QuantitativeExecutionDiagnosticsError,
    _digest,
)
from application.quantitative.ui_service import (
    QuantitativeUiError,
    QuantitativeUiService,
    _QuantitativeWorkflowExecutionFailure,
)


PROJECT = "project"
RUN = "run"
OWNER = "owner"


def _failure(*, stage: str = "RD") -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": PROJECT,
        "run_id": RUN,
        "task_id": "task",
        "stage_id": "quant_analysis",
        "stage": stage,
        "attempt_number": 1,
        "status": "FAILED",
        "failure_category": "RuntimeError",
        "failure_message": "RuntimeError before provider dispatch",
        "terminal_result_persisted": False,
        "last_successful_authority": {
            "key": "analysis_plan_version_id",
            "record_id": "rc-v1",
        },
        "method_version": "q2-13c-1",
    }
    payload["fingerprint"] = _digest(payload)
    return payload


def _call(*, stage: str, status: str) -> dict[str, object]:
    dispatched = status not in {"PLANNED", "FAILED_BEFORE_DISPATCH"}
    returned = status in {"RETURNED", "COMPLETED"}
    payload: dict[str, object] = {
        "call_id": f"{RUN}:{stage}:1",
        "project_id": PROJECT,
        "run_id": RUN,
        "stage": stage,
        "call_ordinal": 1,
        "attempt_ordinal": 1,
        "provider": "openai",
        "model": "bounded",
        "input_authority_fingerprint": f"{stage}-input",
        "status": status,
        "dispatched": dispatched,
        "returned": returned,
        "response_authority_fingerprint": f"{stage}-response" if returned else None,
        "failure_classification": "RuntimeError" if status.startswith("FAILED") else None,
        "failure_message": "RuntimeError after provider dispatch" if status.startswith("FAILED") else None,
        "retry_used": False,
        "retry_ordinal": 0,
        "method_version": "q2-13c-1",
    }
    payload["audit_fingerprint"] = _digest(payload)
    return payload


class _Workflows:
    def __init__(self, task_results: dict[str, object], *, project_id: str = PROJECT):
        self.task_results = copy.deepcopy(task_results)
        self.run = SimpleNamespace(id=RUN, project_id=project_id)

    def get_workflow_run(self, run_id: str):
        if run_id != RUN:
            raise LookupError(run_id)
        return self.run

    def get_task_results(self, run_id: str):
        if run_id != RUN:
            raise LookupError(run_id)
        return copy.deepcopy(self.task_results)


def _ui(workflows: _Workflows, *, owner: str = OWNER) -> QuantitativeUiService:
    projects = Mock()
    projects.get_project.return_value = SimpleNamespace(
        id=PROJECT,
        owner_principal_id=owner,
    )
    return QuantitativeUiService(
        project_service=projects,
        workflow_service=workflows,
        state_service=Mock(),
        digest_provider=Mock(),
        storage_factory=Mock(),
        importers=(),
        finding_generator=Mock(),
        insight_generator=Mock(),
        report_generator=Mock(),
        generation_mode="offline",
        stage_service_factory=Mock(),
    )


class Q213C1FailedRunDiagnosticsTests(unittest.TestCase):
    def test_failed_run_without_terminal_uses_direct_project_run_query(self):
        results = {
            FAILURE_DIAGNOSTIC_KEY: _failure(),
            SEMANTIC_LEDGER_KEY: (),
            "quantitative": {"analysis_plan_version_id": "rc-v1"},
        }
        ui = _ui(_Workflows(results))
        ui.get = Mock(side_effect=AssertionError("Study projection must not be loaded"))

        projection = ui.execution_diagnostics(PROJECT, RUN, owner_id=OWNER)

        self.assertEqual(projection["failure"]["stage"], "RD")
        self.assertEqual(projection["dispatched"], {"QI": 0, "QJ": 0, "QK": 0})
        self.assertEqual(
            projection["failure"]["last_successful_authority"]["record_id"],
            "rc-v1",
        )
        self.assertIsNone(projection["terminal_result_record_id"])
        self.assertFalse(projection["terminal_result_persisted"])
        ui.get.assert_not_called()

    def test_semantic_ledger_and_terminal_absence_survive_restart(self):
        results = {
            FAILURE_DIAGNOSTIC_KEY: _failure(stage="QJ"),
            SEMANTIC_LEDGER_KEY: (
                _call(stage="QI", status="COMPLETED"),
                _call(stage="QJ", status="FAILED_AFTER_DISPATCH"),
            ),
            "quantitative": {},
        }
        durable = _Workflows(results)

        first = _ui(durable).execution_diagnostics(PROJECT, RUN, owner_id=OWNER)
        second = _ui(durable).execution_diagnostics(PROJECT, RUN, owner_id=OWNER)

        self.assertEqual(first, second)
        self.assertEqual(second["dispatched"], {"QI": 1, "QJ": 1, "QK": 0})
        self.assertIsNone(second["terminal_result_record_id"])

    def test_successful_run_and_legacy_one_identifier_form_remain_supported(self):
        results = {
            SEMANTIC_LEDGER_KEY: (),
            "quantitative": {"terminal_result_record_id": "terminal-record"},
        }
        workflows = _Workflows(results, project_id=PROJECT)
        workflows.run.id = PROJECT
        ui = _ui(workflows)
        original_get = workflows.get_workflow_run
        original_results = workflows.get_task_results
        workflows.get_workflow_run = lambda run_id: SimpleNamespace(id=run_id, project_id=PROJECT)
        workflows.get_task_results = lambda run_id: copy.deepcopy(results)

        projection = ui.execution_diagnostics(PROJECT, owner_id=OWNER)

        self.assertEqual(projection["terminal_result_record_id"], "terminal-record")
        self.assertTrue(projection["terminal_result_persisted"])
        workflows.get_workflow_run = original_get
        workflows.get_task_results = original_results

    def test_wrong_project_run_and_corruption_fail_closed(self):
        results = {
            FAILURE_DIAGNOSTIC_KEY: _failure(),
            SEMANTIC_LEDGER_KEY: (),
        }
        with self.assertRaises(QuantitativeUiError):
            _ui(_Workflows(results, project_id="other")).execution_diagnostics(
                PROJECT, RUN, owner_id=OWNER
            )
        with self.assertRaises(QuantitativeUiError):
            _ui(_Workflows(results)).execution_diagnostics(
                PROJECT, RUN, owner_id="other-owner"
            )

        corrupt = copy.deepcopy(results)
        corrupt[FAILURE_DIAGNOSTIC_KEY]["stage"] = "changed"
        with self.assertRaises(QuantitativeExecutionDiagnosticsError):
            _ui(_Workflows(corrupt)).execution_diagnostics(
                PROJECT, RUN, owner_id=OWNER
            )

    def test_public_workflow_failure_preserves_original_exception_as_cause(self):
        ui = _ui(_Workflows({"quantitative": {}}))
        study = SimpleNamespace(
            study_id=PROJECT,
            project_id=PROJECT,
            run_id=RUN,
            state="READY_TO_ANALYZE",
            terminal_result_record_id=None,
            qc_record_id="qc-record",
            qc_approval_id="qc-approval",
            weight_set_record_id=None,
            weight_approval_id=None,
        )
        run = Mock(is_terminal=False, tasks=[])
        run.id = RUN
        run.status.value = "paused"
        context = SimpleNamespace(
            shared_state={
                "quantitative": {},
                "_quantitative_failure_diagnostic": _failure(),
            }
        )
        original = RuntimeError("underlying RD failure")
        ui.get = Mock(return_value=study)
        ui._dataset = Mock(return_value=(Mock(), Mock()))
        ui.state.load.return_value = Mock(fingerprint="qc-fp")
        ui.workflows.get_workflow_run = Mock(return_value=run)
        ui.workflows.get_task_results = Mock(
            return_value={FAILURE_DIAGNOSTIC_KEY: _failure()}
        )
        ui.workflows.get_workflow_run_version = Mock(return_value=1)
        ui.workflows.save_workflow_run = Mock(return_value=2)
        ui._analysis_safe_state = Mock(
            return_value={"study_weighting_mode": "UNWEIGHTED"}
        )
        ui._persist_activation_state = Mock(
            return_value={"study_weighting_mode": "UNWEIGHTED"}
        )
        ui._run_engine = Mock(
            side_effect=_QuantitativeWorkflowExecutionFailure(context, original)
        )

        with patch(
            "application.quantitative.ui_service.QuantitativeApprovalService.require_current"
        ):
            with self.assertRaises(QuantitativeUiError) as captured:
                ui.resume_workflow(PROJECT, owner_id=OWNER)

        self.assertIs(captured.exception.__cause__, original)
        self.assertIn("RD", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
