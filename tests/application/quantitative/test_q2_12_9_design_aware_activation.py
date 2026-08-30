from decimal import Decimal
import tempfile
import unittest
from unittest.mock import Mock

from application.config import ApplicationConfig, ApplicationOverrides
from application.composition_root import create_application_container
from application.quantitative.stage_service_factory import QuantitativeStageServiceFactory
from application.quantitative.ui_service import QuantitativeUiService
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY,
    QuantitativeApprovalService,
    QuantitativeWorkflowError,
    build_quantitative_workflow_template,
)
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.weighting import (
    WeightSet,
    WeightSourceType,
    WeightValidationStatus,
)
from domain.quantitative.workflow import (
    QuantitativeApprovalDecision,
    QuantitativeStudyProjection,
)
from infrastructure.persistence.memory.in_memory_project_repository import InMemoryProjectRepository
from infrastructure.persistence.memory.in_memory_workflow_run_repository import InMemoryWorkflowRunRepository
from infrastructure.persistence.quantitative_analysis_execution_repository import (
    QLQuantitativeAnalysisExecutionRepository,
)
from tests.application.quantitative import test_property_rd_analysis_execution as rd_tests


class _Status:
    value = "paused"


class _Run:
    def __init__(self, run_id):
        self.id = run_id
        self.status = _Status()
        self.tasks = ()
        self.is_terminal = False


class _WorkflowService:
    def __init__(self, run):
        self.run = run
        self.results = {}
        self.version = 0

    def get_workflow_run(self, run_id):
        if run_id != self.run.id:
            raise ValueError("wrong run")
        return self.run

    def get_task_results(self, run_id):
        return dict(self.results)

    def get_workflow_run_version(self, run_id):
        return self.version

    def save_workflow_run(self, run, *, expected_version=None, task_results=None):
        if expected_version != self.version:
            raise ValueError("stale workflow version")
        self.results = dict(task_results or {})
        self.version += 1
        return self.version


class Q2129DesignAwareActivationTests(unittest.TestCase):
    def _factory_fixture(self):
        rd = rd_tests.PropertyRDAnalysisExecutionTests(methodName="runTest")
        rd.setUp()
        state = rd.state
        state.persist(
            rd.dataset,
            record_id="activation-dataset",
            project_id=rd.project,
            run_id=rd.run,
            dataset_version_id=rd.dataset.version_id,
        )
        state.persist(
            rd.codebook,
            record_id="activation-codebook",
            project_id=rd.project,
            run_id=rd.run,
            dataset_version_id=rd.dataset.version_id,
        )
        qc = QualityControlRun(
            "activation-qc",
            rd.dataset.version_id,
            rd.dataset.dataset_fingerprint,
            "questionnaire-fingerprint",
            (),
            (),
            "activation-qc-fingerprint",
        )
        state.persist(
            qc,
            record_id="activation-qc-record",
            project_id=rd.project,
            run_id=rd.run,
            dataset_version_id=rd.dataset.version_id,
        )
        approval = QuantitativeApprovalService(state, rd.rc.digest).record(
            approval_id="activation-qc-approval",
            project_id=rd.project,
            run_id=rd.run,
            subject_type="QC",
            subject_id=qc.run_id,
            subject_fingerprint=qc.fingerprint,
            decision=QuantitativeApprovalDecision.APPROVED,
            actor_id="reviewer",
            decided_at="now",
            rationale="approved",
        )
        factory = QuantitativeStageServiceFactory(
            state_service=state,
            digest_provider=rd.rc.digest,
            storage_factory=lambda project_id, run_id: rd.storage,
            importers=(),
            finding_generator=object(),
            insight_generator=object(),
            report_generator=object(),
            generation_mode="offline",
            analysis_plan_service=rd.rc.service,
            analysis_execution_repository_factory=lambda: QLQuantitativeAnalysisExecutionRepository(state),
        )
        safe = {
            "dataset_record_id": "activation-dataset",
            "codebook_record_id": "activation-codebook",
            "qc_record_id": "activation-qc-record",
            "qc_approval_id": approval.approval_id,
        }
        return rd, factory, safe

    def test_application_resolves_exact_current_rc_before_factory_and_stale_binding_fails(self):
        rd, factory, safe = self._factory_fixture()
        activated = factory.prepare_design_aware_activation(
            project_id=rd.project, run_id=rd.run, safe_state=safe
        )
        self.assertEqual(activated["analysis_execution_mode"], "DESIGN_AWARE_EXECUTION")
        self.assertEqual(activated["analysis_plan_version_id"], "plan-approved")
        self.assertEqual(
            activated["analysis_plan_fingerprint"],
            rd.rc.service.resolve_current_approved(
                project_id=rd.project,
                run_id=rd.run,
                dataset=rd.dataset,
                codebook=rd.codebook,
            ).fingerprint,
        )
        service = factory.create(
            project_id=rd.project, run_id=rd.run, safe_state=activated
        )
        self.assertEqual(service.analysis_plan_authority.version_id, "plan-approved")
        self.assertIsNotNone(service.analysis_execution_service)
        revised = rd.rc.service.revise(
            "plan-approved",
            project_id=rd.project,
            run_id=rd.run,
            new_version_id="plan-v2-draft",
            dataset=rd.dataset,
            codebook=rd.codebook,
            created_at="later",
            created_by="planner",
        )
        reviewed = rd.rc.service.submit_for_review(
            revised.version_id,
            project_id=rd.project,
            run_id=rd.run,
            new_version_id="plan-v2-review",
            actor_id="planner",
            changed_at="later",
        )
        rd.rc.service.approve(
            reviewed.version_id,
            project_id=rd.project,
            run_id=rd.run,
            new_version_id="plan-v2-approved",
            approval_id="plan-v2-approval",
            expected_fingerprint=reviewed.fingerprint,
            actor_id="owner",
            decided_at="latest",
            rationale="approved replacement",
            dataset=rd.dataset,
            codebook=rd.codebook,
        )
        with self.assertRaisesRegex(QuantitativeWorkflowError, "stale"):
            factory.create(
                project_id=rd.project, run_id=rd.run, safe_state=activated
            )
        stale = dict(activated, analysis_plan_fingerprint="stale")
        with self.assertRaisesRegex(QuantitativeWorkflowError, "stale"):
            factory.create(project_id=rd.project, run_id=rd.run, safe_state=stale)

    def test_production_container_public_activation_binds_rc_before_real_factory(self):
        rd, _, _ = self._factory_fixture()
        projects = InMemoryProjectRepository()
        runs = InMemoryWorkflowRunRepository()
        with tempfile.TemporaryDirectory() as root:
            container = create_application_container(
                config=ApplicationConfig(
                    projects_root=root,
                    persistence_backend="memory",
                    deterministic_stage_executors=True,
                    search_provider="deterministic",
                ),
                overrides=ApplicationOverrides(
                    llm_client=Mock(),
                    project_repository=projects,
                    workflow_run_repository=runs,
                    quantitative_state_repository=rd.rc.backing,
                ),
            )
            ui = container.quantitative_ui_service
            container.project_service.create_project(
                "Study", owner_principal_id="owner", project_id=rd.project
            )
            template = build_quantitative_workflow_template()
            container.workflow_service.publish_template_snapshot(
                template, project_id=rd.project
            )
            container.workflow_service.create_workflow_run(
                template,
                project_id=rd.project,
                run_id=rd.run,
                initially_paused=True,
            )
            study = ui._persist_study(
                QuantitativeStudyProjection(
                    rd.project,
                    rd.project,
                    rd.run,
                    "Study",
                    "Description",
                    "WEIGHTING_REQUIRED",
                    dataset_record_id="activation-dataset",
                    codebook_record_id="activation-codebook",
                    qc_record_id="activation-qc-record",
                    qc_approval_id="activation-qc-approval",
                )
            )
            ui.durable_workflow_service = Mock()
            activated = ui.activate_design_aware_workflow(
                study.study_id, owner_id="owner"
            )
            safe = container.workflow_service.get_task_results(rd.run)[
                QUANTITATIVE_SAFE_STATE_KEY
            ]
            self.assertEqual(activated.state, "ANALYZING")
            self.assertEqual(
                safe["analysis_execution_mode"], "DESIGN_AWARE_EXECUTION"
            )
            self.assertEqual(safe["study_weighting_mode"], "UNWEIGHTED")
            self.assertNotIn("weight_set_record_id", safe)
            self.assertNotIn("weight_approval_id", safe)
            skipped = ui.durable_workflow_service.activate_paused_run.call_args.kwargs[
                "skipped_task_definition_ids"
            ]
            self.assertEqual(
                skipped, ("quant_weightset", "quant_weight_approval")
            )
            service = ui.stage_service_factory.create(
                project_id=rd.project, run_id=rd.run, safe_state=safe
            )
            self.assertEqual(
                service.analysis_plan_authority.version_id,
                safe["analysis_plan_version_id"],
            )
            self.assertEqual(
                service.analysis_plan_authority.fingerprint,
                safe["analysis_plan_fingerprint"],
            )
            self.assertIsNotNone(service.analysis_execution_service)
            container.shutdown()

    def test_explicit_unweighted_activation_rejects_contradictory_weightset(self):
        rd, factory, safe = self._factory_fixture()
        activated = factory.prepare_design_aware_activation(
            project_id=rd.project, run_id=rd.run, safe_state=safe
        )
        self.assertEqual(activated["study_weighting_mode"], "UNWEIGHTED")
        contradictory = dict(
            activated,
            weight_set_record_id="forbidden-weightset",
            weight_set_id="forbidden",
            weight_set_fingerprint="forbidden",
            weight_approval_id="forbidden-approval",
        )
        with self.assertRaisesRegex(QuantitativeWorkflowError, "unweighted"):
            factory.create(
                project_id=rd.project,
                run_id=rd.run,
                safe_state=contradictory,
            )

    def _ui(self, *, prepare):
        project_id = run_id = study_id = "study"
        study = QuantitativeStudyProjection(
            study_id,
            project_id,
            run_id,
            "Study",
            "Description",
            "READY_TO_ANALYZE",
            dataset_record_id="dataset-record",
            codebook_record_id="codebook-record",
            qc_record_id="qc-record",
            qc_approval_id="qc-approval",
            weight_set_record_id="weight-record",
            weight_approval_id="weight-approval",
        )
        dataset = Mock(
            version_id="dataset-v1",
            dataset_fingerprint="dataset-fp",
            parent_version_id=None,
        )
        codebook = Mock(codebook_version_id="codebook-v1")
        qc = Mock(fingerprint="qc-fp")
        weights = Mock(weight_set_id="weights-v1", reproducibility_fingerprint="weights-fp")
        run = _Run(run_id)
        workflows = _WorkflowService(run)
        factory = Mock()
        factory.prepare_design_aware_activation.side_effect = prepare
        durable = Mock()
        ui = QuantitativeUiService(
            project_service=Mock(),
            workflow_service=workflows,
            state_service=Mock(),
            digest_provider=Mock(),
            storage_factory=Mock(),
            importers=(),
            finding_generator=Mock(),
            insight_generator=Mock(),
            report_generator=Mock(),
            generation_mode="offline",
            stage_service_factory=factory,
            durable_workflow_service=durable,
        )
        ui.get = Mock(return_value=study)
        ui._dataset = Mock(return_value=(dataset, codebook))
        def load(record_id, *, project_id, expected_type):
            if expected_type is QualityControlRun:
                return qc
            if expected_type is WeightSet:
                return weights
            fingerprint = "qc-fp" if record_id == "qc-approval" else "weights-fp"
            return Mock(
                current=True,
                subject_fingerprint=fingerprint,
                decision=QuantitativeApprovalDecision.APPROVED,
            )

        ui.state.load.side_effect = load
        ui._save = Mock(side_effect=lambda value: value)
        return ui, workflows, factory, durable

    def test_public_design_aware_intent_persists_application_resolved_mode_and_rc(self):
        def prepare(*, project_id, run_id, safe_state):
            return dict(
                safe_state,
                analysis_execution_mode="DESIGN_AWARE_EXECUTION",
                analysis_plan_version_id="rc-approved-v1",
                analysis_plan_fingerprint="rc-fingerprint",
            )

        ui, workflows, factory, durable = self._ui(prepare=prepare)
        result = ui.activate_design_aware_workflow("study", owner_id="owner")
        safe = workflows.results[QUANTITATIVE_SAFE_STATE_KEY]
        self.assertEqual(result.state, "ANALYZING")
        self.assertEqual(safe["analysis_execution_mode"], "DESIGN_AWARE_EXECUTION")
        self.assertEqual(safe["analysis_plan_version_id"], "rc-approved-v1")
        self.assertEqual(safe["analysis_plan_fingerprint"], "rc-fingerprint")
        self.assertEqual(factory.prepare_design_aware_activation.call_count, 2)
        durable.activate_paused_run.assert_called_once()

    def test_failed_design_resolution_has_no_dataset_only_fallback(self):
        def fail(**kwargs):
            raise QuantitativeWorkflowError("no current approved Analysis Plan")

        ui, workflows, _, durable = self._ui(prepare=fail)
        with self.assertRaisesRegex(Exception, "Analysis Plan"):
            ui.activate_design_aware_workflow("study", owner_id="owner")
        self.assertEqual(workflows.results, {})
        durable.activate_paused_run.assert_not_called()

    def test_dataset_only_resume_persists_explicit_mode_without_rc(self):
        ui, workflows, factory, durable = self._ui(prepare=lambda **kwargs: kwargs)
        result = ui.resume_workflow("study", owner_id="owner")
        safe = workflows.results[QUANTITATIVE_SAFE_STATE_KEY]
        self.assertEqual(result.state, "ANALYZING")
        self.assertEqual(
            safe["analysis_execution_mode"],
            "DATASET_ONLY_EXPLORATORY_EXECUTION",
        )
        self.assertNotIn("analysis_plan_version_id", safe)
        self.assertNotIn("analysis_plan_fingerprint", safe)
        factory.prepare_design_aware_activation.assert_not_called()
        durable.activate_paused_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
