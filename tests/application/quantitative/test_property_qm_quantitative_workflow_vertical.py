from __future__ import annotations

import unittest
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY,
    QUANTITATIVE_STAGE_SERVICE_KEY,
    STAGES,
    QuantitativeApprovalService,
    QuantitativeApprovalRequired,
    QuantitativeStageExecutor,
    QuantitativeWorkflowError,
    build_quantitative_workflow_template,
    validate_safe_workflow_state,
    resume_after_quantitative_approval,
)
from application.quantitative.vertical_service import QuantitativeVerticalPlan, RealQuantitativeStageService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import QuantitativeInsightSynthesisService, QuantitativeInsightValidator
from application.quantitative.report_composition import QuantitativeReportCompositionService, QuantitativeReportValidator
from application.quantitative.quality_control import build_questionnaire_snapshot, build_cleaning_decision, build_cleaning_decision_set
from application.runtime.workflow_completion_policy import WorkflowCompletionPolicy
from application.task_executor import TaskExecutor
from application.task_lifecycle_manager import TaskLifecycleManager
from application.task_scheduler import TaskScheduler
from application.workflow_engine import WorkflowEngine
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.quantitative.workflow import (
    QuantitativeApprovalDecision,
    QuantitativeTerminalOutcome,
    QuantitativeTerminalResult,
)
from domain.quantitative.analysis import AnalysisSpecification, CrossTabAnalysisSpecification, NumericAnalysisSpecification, NpsAnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, DatasetVersion, VariableRole, VariableType
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.report import QuantitativeReportCompositionResult
from domain.quantitative.quality import ApprovalState, CleaningAction
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from infrastructure.quantitative.importers.sav_pyreadstat_adapter import SavPyreadstatAdapter
from infrastructure.quantitative.storage.in_memory_dataset_storage import InMemoryDatasetStorage
from infrastructure.quantitative.storage.protected_file_dataset_storage import ProtectedFileDatasetStorage
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes
from runtime.workflow_context import WorkflowContext


class _VerticalStageService:
    def __init__(self, state_service: QuantitativeStateService):
        self.calls: list[str] = []
        self.state_service = state_service

    def execute_stage(self, stage_id, *, project_id, run_id, safe_state):
        self.calls.append(stage_id)
        state = dict(safe_state)
        state[f"{stage_id}_fingerprint"] = f"fp-{stage_id}"
        if stage_id == "quant_import":
            state.update(dataset_version_id="dataset-v1", dataset_fingerprint="dataset-fp")
        if stage_id == "quant_weightset":
            state.update(weight_set_id="weights-v1", weight_set_fingerprint="weights-fp")
        if stage_id == "quant_analysis":
            state["statistical_result_manifest_id"] = "results-v1"
        if stage_id == "quant_complete":
            terminal = QuantitativeTerminalResult(
                result_id="terminal-v1", project_id=project_id, run_id=run_id,
                methodology="QUANTITATIVE", dataset_version_id="dataset-v1",
                dataset_fingerprint="dataset-fp", qc_status="APPROVED",
                cleaning_lineage=(), weight_set_id="weights-v1",
                weight_set_fingerprint="weights-fp", weight_approval_id="wa-v1",
                statistical_result_ids=("result-1",), accepted_finding_count=1,
                rejected_finding_count=1, accepted_insight_count=1,
                rejected_insight_count=1, report_id="report-v1",
                report_status="ACCEPTED", limitations=("synthetic fixture",),
                execution_status="COMPLETED",
                terminal_outcome=QuantitativeTerminalOutcome.COMPLETED,
                fingerprint="terminal-fp",
            )
            self.state_service.persist(
                terminal, record_id=terminal.result_id, project_id=project_id,
                run_id=run_id, accepted=True,
            )
            state["terminal_result_id"] = terminal.result_id
        return state


class _ApprovalCheckpointService(_VerticalStageService):
    def __init__(self, state_service):
        super().__init__(state_service)
        self.approved = False

    def execute_stage(self, stage_id, *, project_id, run_id, safe_state):
        if stage_id == "quant_qc_approval" and not self.approved:
            raise QuantitativeApprovalRequired(
                subject_type="QC", subject_id="qc-1", subject_fingerprint="qc-fp"
            )
        return super().execute_stage(
            stage_id, project_id=project_id, run_id=run_id, safe_state=safe_state
        )


def _bundle(prompt, marker):
    return json.loads(prompt.split(marker, 1)[1])


class _FindingGenerator:
    identity = "qm-offline-findings-v1"
    def generate(self, prompt):
        results = _bundle(prompt, "AUTHORITATIVE_BUNDLE=")["statistical_results"]
        percentage = next(item for item in results if "DESCRIPTIVE_VALUE" in item["allowed_claim_types"])
        weighted = next(item for item in results if item["weighting_status"] == "WEIGHTED" and "DESCRIPTIVE_VALUE" in item["allowed_claim_types"])
        def proposal(item, *, invalid=False):
            display = "999.0" if invalid else item["display_value_1dp"]
            return {"claim_type":"DESCRIPTIVE_VALUE", "finding_text":f"Supported aggregate was {display}.", "selected_result_ids":[item["result_id"]], "selected_comparison_ids":[], "limitation_note":"Synthetic aggregate."}
        return {"proposals":[proposal(percentage), proposal(weighted), proposal(percentage, invalid=True)]}


class _InsightGenerator:
    identity = "qm-offline-insights-v1"
    def generate(self, prompt):
        findings = _bundle(prompt, "ACCEPTED_FINDINGS=")
        first=findings[0]
        base={"insight_type":"SYNTHESIS", "supporting_finding_ids":[first["finding_id"]], "direction":None, "limitation_note":"Synthetic aggregate."}
        valid=dict(base, insight_text=f"Supported result was {first['display_value']}.", referenced_display_values=[first["display_value"]])
        invalid=dict(base, insight_text="Unsupported result was 999.0.", referenced_display_values=["999.0"])
        return {"proposals":[valid, invalid]}


class _ReportGenerator:
    identity = "qm-offline-report-v1"
    def generate(self, prompt):
        support=_bundle(prompt, "APPROVED_SUPPORT="); finding=support["findings"][0]; insight=support["insights"][0]
        value=finding["display_value"]
        section={"section_id":"section-1", "section_type":"KEY_FINDINGS", "title":"Results", "narrative":f"Supported result was {value}.", "finding_refs":[finding["finding_id"]], "finding_fingerprints":{finding["finding_id"]:finding["validation_fingerprint"]}, "insight_refs":[insight["insight_id"]], "insight_fingerprints":{insight["insight_id"]:insight["validation_fingerprint"]}, "referenced_display_values":[value], "authoritative_result_refs":finding["result_refs"], "authoritative_table_refs":[], "weighting_status":finding["weighting"], "filter_definition":finding["filter"], "base_definition":finding["base"], "direction":None}
        return {"title":"Synthetic Quantitative Report", "finding_refs":[finding["finding_id"]], "finding_fingerprints":{finding["finding_id"]:finding["validation_fingerprint"]}, "insight_refs":[insight["insight_id"]], "insight_fingerprints":{insight["insight_id"]:insight["validation_fingerprint"]}, "sections":[section]}


class _InterruptAfterAnalysisService(RealQuantitativeStageService):
    def execute_stage(self, stage_id, *, project_id, run_id, safe_state):
        if stage_id == "quant_findings":
            raise QuantitativeApprovalRequired(subject_type="RESTART_CHECKPOINT", subject_id=safe_state["analysis_manifest_record_id"], subject_fingerprint=safe_state["analysis_manifest_record_id"])
        return super().execute_stage(stage_id, project_id=project_id, run_id=run_id, safe_state=safe_state)


class PropertyQMTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()
        self.repository = InMemoryQuantitativeStateRepository()
        self.state_service = QuantitativeStateService(
            repository=self.repository, digest_provider=self.digest
        )
        self.template = build_quantitative_workflow_template()

    def _run(self, run, service, shared_state=None):
        resolver = Mock()
        resolver.resolve.return_value = QuantitativeStageExecutor()
        engine = WorkflowEngine(
            scheduler=TaskScheduler(),
            task_executor=TaskExecutor(
                resolver=resolver, lifecycle=TaskLifecycleManager()
            ),
            completion_policy=WorkflowCompletionPolicy(),
        )
        context = WorkflowContext(
            project=Project(id="project-1", name="Synthetic study"),
            workflow_template=self.template, workflow_run=run,
            services={QUANTITATIVE_STAGE_SERVICE_KEY: service},
            shared_state=shared_state or {},
        )
        return engine.run(context)

    def test_template_is_first_class_linear_quantitative_dag(self):
        definitions = self.template.task_definitions
        self.assertEqual([item.id for item in definitions], [item[0] for item in STAGES])
        self.assertEqual(definitions[0].depends_on, [])
        for previous, current in zip(definitions, definitions[1:]):
            self.assertEqual(current.depends_on, [previous.id])
            self.assertEqual(current.metadata["methodology"], "QUANTITATIVE")
        serialized = repr(
            [(item.id, item.name, item.executor_id, item.metadata) for item in definitions]
        ).casefold()
        for forbidden in ("source", "evidence", "informationneed", "sufficiency", "search"):
            self.assertNotIn(forbidden, serialized)

    def test_vertical_runs_through_neutral_engine_and_persists_terminal_result(self):
        run = WorkflowRunFactory(TaskFactory()).create(
            self.template, run_id="run-1", project_id="project-1"
        )
        service = _VerticalStageService(self.state_service)
        context = self._run(run, service)
        self.assertEqual(service.calls, [item[0] for item in STAGES])
        self.assertEqual(run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["terminal_result_id"], "terminal-v1")
        terminal = self.state_service.load(
            "terminal-v1", project_id="project-1", expected_type=QuantitativeTerminalResult
        )
        self.assertEqual(terminal.terminal_outcome, QuantitativeTerminalOutcome.COMPLETED)

    def test_restart_resume_skips_completed_authority_without_duplication(self):
        run = WorkflowRunFactory(TaskFactory()).create(
            self.template, run_id="run-restart", project_id="project-1"
        )
        # Durable reload reconstructs task states; already completed stages remain terminal.
        for task in run.tasks[:6]:
            task.ready() if task.status is TaskStatus.CREATED else None
            task.start(); task.complete()
        run.ready(); run.start()
        service = _VerticalStageService(self.state_service)
        self._run(run, service)
        self.assertEqual(service.calls, [item[0] for item in STAGES[6:]])
        self.assertNotIn("quant_import", service.calls)
        self.assertNotIn("quant_weightset", service.calls)

    def test_approval_checkpoint_pauses_and_resumes_same_task(self):
        run = WorkflowRunFactory(TaskFactory()).create(
            self.template, run_id="run-approval", project_id="project-1"
        )
        service = _ApprovalCheckpointService(self.state_service)
        context = self._run(run, service)
        self.assertEqual(run.status, WorkflowStatus.PAUSED)
        self.assertEqual(context.current_task.definition_id, "quant_qc_approval")
        self.assertEqual(context.current_task.status, TaskStatus.PAUSED)
        self.assertEqual(
            context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["awaiting_approval_subject_id"],
            "qc-1",
        )
        service.approved = True
        resume_after_quantitative_approval(context)
        completed = self._run(run, service, context.shared_state)
        self.assertEqual(completed.workflow_run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(service.calls.count("quant_import"), 1)

    def test_safe_workflow_state_rejects_rows_pii_bytes_and_complex_payloads(self):
        for payload in (
            {"rows": "hidden"}, {"PII": "hidden"}, {"raw_bytes": "hidden"},
            {"dataset_id": ["not", "safe"]},
        ):
            with self.assertRaises(QuantitativeWorkflowError):
                validate_safe_workflow_state(payload)

    def test_qc_and_weight_approvals_are_durable_and_fingerprint_bound(self):
        approvals = QuantitativeApprovalService(self.state_service, self.digest)
        for approval_id, subject_type in (("qc-a", "QC"), ("weight-a", "WEIGHTSET")):
            approvals.record(
                approval_id=approval_id, project_id="project-1", run_id="run-1",
                subject_type=subject_type, subject_id="subject-1",
                subject_fingerprint="subject-fp", decision=QuantitativeApprovalDecision.APPROVED,
                actor_id="analyst-1", decided_at="2026-08-20T00:00:00Z",
                rationale="reviewed synthetic fixture",
            )
            recreated = QuantitativeApprovalService(
                QuantitativeStateService(repository=self.repository, digest_provider=self.digest),
                self.digest,
            )
            self.assertEqual(
                recreated.require_current(
                    approval_id, project_id="project-1", subject_fingerprint="subject-fp"
                ).actor_id,
                "analyst-1",
            )
            with self.assertRaises(QuantitativeWorkflowError):
                recreated.require_current(
                    approval_id, project_id="project-1", subject_fingerprint="changed-fp"
                )

    def test_rejected_approval_and_wrong_project_fail_closed(self):
        approvals = QuantitativeApprovalService(self.state_service, self.digest)
        approvals.record(
            approval_id="rejected", project_id="project-1", run_id="run-1",
            subject_type="QC", subject_id="qc-1", subject_fingerprint="qc-fp",
            decision=QuantitativeApprovalDecision.REJECTED, actor_id="analyst-1",
            decided_at="2026-08-20T00:00:00Z", rationale="issues remain",
        )
        for project_id in ("project-1", "other-project"):
            with self.assertRaises((QuantitativeWorkflowError, Exception)):
                approvals.require_current(
                    "rejected", project_id=project_id, subject_fingerprint="qc-fp"
                )

    def test_real_sav_runs_through_qa_to_qk_services(self):
        raw = sav_sample_bytes()
        overrides = {
            "mychar": VariableOverride(variable_type=VariableType.TECHNICAL_ID, role=VariableRole.TECHNICAL_ID),
            "mylabl": VariableOverride(variable_type=VariableType.CATEGORICAL, role=VariableRole.RESPONSE),
            "myord": VariableOverride(variable_type=VariableType.DEMOGRAPHIC, role=VariableRole.DEMOGRAPHIC),
            "mynum": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.RESPONSE),
        }
        preview_storage = InMemoryDatasetStorage()
        preview = QuantitativeDatasetImportService(importers=(SavPyreadstatAdapter(),), storage=preview_storage, digest_provider=self.digest).import_bytes(raw, filename="sample.sav", dataset_format=DatasetFormat.SAV, dataset_id="qm-sav", project_id="project-1", run_id="run-real", overrides=overrides)
        variables = {item.name: item for item in preview.codebook.variables}
        questionnaire = build_questionnaire_snapshot(snapshot_id="qm-questionnaire", version="1", codebook_version_id=preview.codebook.codebook_version_id, question_variable_bindings=tuple((item.name, item.variable_id) for item in preview.codebook.variables), answer_domains=((variables["mynum"].variable_id,(0,7,8,9,10)),), digest_provider=self.digest)
        refs=preview_storage.get_respondent_lineage(preview.dataset_version.version_id)
        old_values=(1.1,1.2,-1000.3,-1.4,1000.3); new_values=(0,7,8,9,10)
        decisions=tuple(build_cleaning_decision(parent=preview.dataset_version, action=CleaningAction.RECODE, affected_refs=(ref,), variable_ids=(variables["mynum"].variable_id,), transformation=(("from",old),("to",new)), rationale="approved synthetic scale recode", actor_id="analyst", issue_ids=(), digest_provider=self.digest) for ref,old,new in zip(refs,old_values,new_values))
        cleaning=build_cleaning_decision_set(parent=preview.dataset_version, decisions=decisions, approval_state=ApprovalState.APPROVED, approver_id="analyst", approved_at="2026-08-20T00:00:00Z", digest_provider=self.digest)
        plan = QuantitativeVerticalPlan(
            dataset_bytes=raw, filename="sample.sav", dataset_id="qm-sav",
            variable_overrides=overrides, questionnaire=questionnaire,
            imported_weight_rows=(("a",1),("b",2),("c",1),("d",2),("e",1)),
            weight_source_checksum="synthetic-weight-vector-v1",
            one_way=AnalysisSpecification("one-way", variables["mylabl"].variable_id),
            cross_tab=CrossTabAnalysisSpecification("cross-tab", variables["mylabl"].variable_id, weighting_status="WEIGHTED", column_variable_id=variables["myord"].variable_id),
            numeric=NumericAnalysisSpecification("numeric", variables["mynum"].variable_id, weighting_status="WEIGHTED"),
            nps=NpsAnalysisSpecification("nps", variables["mynum"].variable_id, weighting_status="WEIGHTED"),
            cleaning_decision_set=cleaning,
        )
        with tempfile.TemporaryDirectory() as directory:
            storage = ProtectedFileDatasetStorage(root=Path(directory), project_id="project-1", run_id="run-real", digest_provider=self.digest)
            approval_service = QuantitativeApprovalService(self.state_service, self.digest)
            service = _InterruptAfterAnalysisService(
                plan=plan, storage=storage, digest_provider=self.digest,
                state_service=self.state_service, approval_service=approval_service,
                finding_service=QuantitativeFindingGenerationService(generator=_FindingGenerator(), support_validator=QuantitativeFindingSupportValidator(digest_provider=self.digest), digest_provider=self.digest),
                insight_service=QuantitativeInsightSynthesisService(generator=_InsightGenerator(), validator=QuantitativeInsightValidator(digest_provider=self.digest), digest_provider=self.digest),
                report_service=QuantitativeReportCompositionService(generator=_ReportGenerator(), validator=QuantitativeReportValidator(digest_provider=self.digest), digest_provider=self.digest),
                importers=(SavPyreadstatAdapter(),),
            )
            run = WorkflowRunFactory(TaskFactory()).create(self.template, run_id="run-real", project_id="project-1")
            context = self._run(run, service)
            self.assertEqual(context.current_task.definition_id, "quant_qc_approval")
            qc_approval = approval_service.record(approval_id="qm-qc-approval", project_id="project-1", run_id="run-real", subject_type="QC", subject_id=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["qc_record_id"], subject_fingerprint=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["qc_fingerprint"], decision=QuantitativeApprovalDecision.APPROVED, actor_id="analyst", decided_at="2026-08-20T00:00:00Z", rationale="approved")
            context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["qc_approval_id"] = qc_approval.approval_id
            resume_after_quantitative_approval(context); context = self._run(run, service, context.shared_state)
            self.assertEqual(context.current_task.definition_id, "quant_cleaning")
            cleaned_safe=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]
            cleaned_approval=approval_service.record(approval_id="qm-cleaned-qc-approval", project_id="project-1", run_id="run-real", subject_type="QC", subject_id=cleaned_safe["qc_record_id"], subject_fingerprint=cleaned_safe["qc_fingerprint"], decision=QuantitativeApprovalDecision.APPROVED, actor_id="analyst", decided_at="2026-08-20T00:00:00Z", rationale="cleaned QC approved")
            cleaned_safe["cleaned_qc_approval_id"]=cleaned_approval.approval_id
            resume_after_quantitative_approval(context); context=self._run(run, service, context.shared_state)
            self.assertEqual(context.current_task.definition_id, "quant_weight_approval")
            safe=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]
            weight_approval=approval_service.record(approval_id="qm-weight-approval", project_id="project-1", run_id="run-real", subject_type="WEIGHTSET", subject_id=safe["weight_set_id"], subject_fingerprint=safe["weight_set_fingerprint"], decision=QuantitativeApprovalDecision.APPROVED, actor_id="analyst", decided_at="2026-08-20T00:00:00Z", rationale="approved")
            safe["weight_approval_id"]=weight_approval.approval_id
            resume_after_quantitative_approval(context); context=self._run(run, service, context.shared_state)
            self.assertEqual(context.current_task.definition_id,"quant_findings")
            safe=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]
            analysis_record=safe["analysis_manifest_record_id"]
            records_before=len(self.repository.list_for_run("run-real",project_id="project-1"))
            recreated_storage=ProtectedFileDatasetStorage(root=Path(directory),project_id="project-1",run_id="run-real",digest_provider=self.digest)
            recreated_state=QuantitativeStateService(repository=self.repository,digest_provider=self.digest)
            service=RealQuantitativeStageService(plan=plan,storage=recreated_storage,digest_provider=self.digest,state_service=recreated_state,approval_service=QuantitativeApprovalService(recreated_state,self.digest),finding_service=QuantitativeFindingGenerationService(generator=_FindingGenerator(),support_validator=QuantitativeFindingSupportValidator(digest_provider=self.digest),digest_provider=self.digest),insight_service=QuantitativeInsightSynthesisService(generator=_InsightGenerator(),validator=QuantitativeInsightValidator(digest_provider=self.digest),digest_provider=self.digest),report_service=QuantitativeReportCompositionService(generator=_ReportGenerator(),validator=QuantitativeReportValidator(digest_provider=self.digest),digest_provider=self.digest),importers=(SavPyreadstatAdapter(),))
            resume_after_quantitative_approval(context); context=self._run(run,service,context.shared_state)
            self.assertEqual(context.workflow_run.status, WorkflowStatus.COMPLETED)
            safe=context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]
            self.assertEqual(safe["terminal_authority_status"], "COMPLETE")
            self.assertEqual(safe["analysis_manifest_record_id"],analysis_record)
            self.assertGreater(len(self.repository.list_for_run("run-real",project_id="project-1")),records_before)
            final_dataset=self.state_service.load(safe["dataset_record_id"],project_id="project-1",expected_type=DatasetVersion)
            terminal=self.state_service.load(safe["terminal_result_record_id"],project_id="project-1",expected_type=QuantitativeTerminalResult)
            self.assertNotEqual(final_dataset.version_id,preview.dataset_version.version_id)
            self.assertEqual(final_dataset.parent_version_id,preview.dataset_version.version_id)
            self.assertEqual(terminal.dataset_fingerprint,final_dataset.dataset_fingerprint)
            findings=self.state_service.load(safe["finding_generation_record_id"], project_id="project-1", expected_type=QuantitativeFindingGenerationResult)
            insights=self.state_service.load(safe["insight_generation_record_id"], project_id="project-1", expected_type=QuantitativeInsightGenerationResult)
            report=self.state_service.load(safe["report_composition_record_id"], project_id="project-1", expected_type=QuantitativeReportCompositionResult)
            self.assertEqual((len(findings.accepted_findings),len(findings.rejected_findings)),(2,1))
            self.assertEqual((len(insights.accepted_insights),len(insights.rejected_insights)),(1,1))
            self.assertIsNotNone(report.accepted_report)
            self.assertEqual((terminal.accepted_finding_count,terminal.rejected_finding_count),(2,1))


if __name__ == "__main__":
    unittest.main()
