from __future__ import annotations

import json
import tempfile
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.quantitative.vertical_service import RealQuantitativeStageService
from application.quantitative.workflow import (
    QUANTITATIVE_SAFE_STATE_KEY,
    QUANTITATIVE_STAGE_SERVICE_KEY,
)
from domain.quantitative.workflow import QuantitativeTerminalResult
from domain.quantitative.dataset import DatasetVersion
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.weighting import WeightSet
from domain.workflow_status import WorkflowStatus
from infrastructure.quantitative.llm_generators import (
    LLMQuantitativeFindingGenerator,
    LLMQuantitativeInsightGenerator,
    LLMQuantitativeReportGenerator,
)
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qp_production_llm_adapters import (
    RecordingLLMClient,
)
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class PropertyQsDurableWorkerResolutionTests(ApiTestCase):
    def _principal(self) -> str:
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def _ready_study(self, key: str):
        created = self.client.post(
            "/ui/quantitative/studies",
            data={
                "title": "QS synthetic worker study",
                "description": "offline worker acceptance",
                "submission_key": key,
            },
            follow_redirects=False,
        )
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={
                "dataset": (
                    "sample.sav",
                    sav_sample_bytes(),
                    "application/octet-stream",
                )
            },
            follow_redirects=False,
        )
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False
        )
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/cleaning",
            data={
                "variable_name": "mynum",
                "replacements_json": json.dumps(
                    {"1.1": 0, "1.2": 7, "-1000.3": 8, "-1.4": 9, "1000.3": 10}
                ),
            },
            follow_redirects=False,
        )
        service = self.container.quantitative_ui_service
        study = service.get(study_id, owner_id=self._principal())
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={
                "fingerprint": study.qc_record_id.rsplit(":", 1)[-1],
                "decision": "APPROVED",
                "rationale": "current synthetic QC",
            },
            follow_redirects=False,
        )
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/target-margins",
            data={
                "targets_json": json.dumps(
                    {"myord": {"1.0": 60, "2.0": 20, "3.0": 20}}
                )
            },
            follow_redirects=False,
        )
        study = service.get(study_id, owner_id=self._principal())
        self.client.post(
            f"/ui/quantitative/studies/{study_id}/weight-approval",
            data={
                "fingerprint": study.weight_set_record_id.rsplit(":", 1)[-1],
                "decision": "APPROVED",
                "rationale": "current synthetic weighting",
            },
            follow_redirects=False,
        )
        return service.get(study_id, owner_id=self._principal())

    def _safe_state(self, study) -> dict[str, str]:
        state = self.container.quantitative_ui_service.state
        dataset = state.load(
            study.dataset_record_id,
            project_id=study.project_id,
            expected_type=DatasetVersion,
        )
        qc = state.load(
            study.qc_record_id,
            project_id=study.project_id,
            expected_type=QualityControlRun,
        )
        weights = state.load(
            study.weight_set_record_id,
            project_id=study.project_id,
            expected_type=WeightSet,
        )
        return {
            "dataset_record_id": study.dataset_record_id,
            "codebook_record_id": study.codebook_record_id,
            "dataset_version_id": dataset.version_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "qc_record_id": study.qc_record_id,
            "qc_fingerprint": qc.fingerprint,
            "qc_approval_id": study.qc_approval_id,
            "cleaning_status": "CLEANED",
            "weight_set_record_id": study.weight_set_record_id,
            "weight_set_id": weights.weight_set_id,
            "weight_set_fingerprint": weights.reproducibility_fingerprint,
            "weight_approval_id": study.weight_approval_id,
        }

    def _activate(self, study):
        run = self.container.workflow_service.get_workflow_run(study.run_id)
        return self.container.durable_workflow_service.activate_paused_run(
            study.run_id,
            shared_state={QUANTITATIVE_SAFE_STATE_KEY: self._safe_state(study)},
            completed_task_definition_ids=tuple(
                task.definition_id for task in run.tasks[:5]
            ),
        )

    def test_paused_run_is_not_claimed_then_authorized_worker_runs_real_service(self):
        study = self._ready_study("qs-worker")
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study.run_id).status,
            WorkflowStatus.PAUSED,
        )
        self.assertFalse(
            self.container.worker_execution_service.process_once("qs-worker")
        )

        context = self._activate(study)
        self.assertIs(context.workflow_run.status, WorkflowStatus.RUNNING)
        self.assertIsInstance(
            context.services[QUANTITATIVE_STAGE_SERVICE_KEY],
            RealQuantitativeStageService,
        )
        durable = self.container.workflow_service.get_task_results(study.run_id)
        self.assertNotIn(QUANTITATIVE_STAGE_SERVICE_KEY, repr(durable))
        for forbidden in ("respondents", "pseudonym_bindings", "raw_bytes", "pii"):
            self.assertNotIn(forbidden, repr(durable).casefold())

        self.assertTrue(
            self.container.worker_execution_service.process_once("qs-worker")
        )
        completed = self.container.workflow_service.get_workflow_run(study.run_id)
        self.assertIs(completed.status, WorkflowStatus.COMPLETED)
        terminals = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id,
            project_id=study.project_id,
            expected_type=QuantitativeTerminalResult,
        )
        self.assertEqual(len(terminals), 1)
        self.assertFalse(
            self.container.worker_execution_service.process_once("qs-worker")
        )
        self.assertEqual(
            len(
                self.container.quantitative_ui_service.state.list_for_run(
                    study.run_id,
                    project_id=study.project_id,
                    expected_type=QuantitativeTerminalResult,
                )
            ),
            1,
        )

    def test_recovered_context_rebuilds_service_without_persisting_it(self):
        study = self._ready_study("qs-recovery")
        first = self._activate(study)
        second = self.container.durable_workflow_service._load_context(study.run_id)
        first_service = first.services[QUANTITATIVE_STAGE_SERVICE_KEY]
        second_service = second.services[QUANTITATIVE_STAGE_SERVICE_KEY]
        self.assertIsInstance(first_service, RealQuantitativeStageService)
        self.assertIsInstance(second_service, RealQuantitativeStageService)
        self.assertIsNot(first_service, second_service)
        self.assertNotIn(
            QUANTITATIVE_STAGE_SERVICE_KEY,
            repr(self.container.workflow_service.get_task_results(study.run_id)),
        )

    def test_authorized_qo_resume_activates_worker_without_inline_execution(self):
        study = self._ready_study("qs-qo-resume")
        service = self.container.quantitative_ui_service
        service.durable_workflow_service = self.container.durable_workflow_service
        response = self.client.post(
            f"/ui/quantitative/studies/{study.study_id}/resume",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study.run_id).status,
            WorkflowStatus.RUNNING,
        )
        self.assertFalse(
            service.state.list_for_run(
                study.run_id,
                project_id=study.project_id,
                expected_type=QuantitativeTerminalResult,
            )
        )
        self.assertTrue(
            self.container.worker_execution_service.process_once("qs-qo-worker")
        )
        result = self.client.get(
            f"/ui/quantitative/studies/{study.study_id}/result.json"
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["terminal_status"], "COMPLETED")

    def test_missing_factory_and_wrong_project_fail_closed(self):
        study = self._ready_study("qs-fail-closed")
        resolver = self.container.durable_workflow_service._context_service_resolver
        with self.assertRaisesRegex(ValueError, "project/run"):
            resolver.factory.create(
                project_id="wrong-project",
                run_id=study.run_id,
                safe_state=self._safe_state(study),
            )
        with self.assertRaisesRegex(ValueError, "project/run"):
            resolver.factory.create(
                project_id=study.project_id,
                run_id="wrong-run",
                safe_state=self._safe_state(study),
            )
        self.container.durable_workflow_service._context_service_resolver = None
        self._activate(study)
        self.assertTrue(
            self.container.worker_execution_service.process_once("qs-no-service")
        )
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study.run_id).status,
            WorkflowStatus.FAILED,
        )

    def test_production_factory_uses_qp_adapters_and_offline_is_explicit(self):
        client = RecordingLLMClient()
        container = create_application_container(
            config=ApplicationConfig(
                projects_root=tempfile.mkdtemp(),
                persistence_backend="memory",
                background_execution_mode="embedded",
                deterministic_stage_executors=False,
                search_provider="deterministic",
            ),
            overrides=ApplicationOverrides(
                llm_client=client,
                quantitative_llm_client=client,
            ),
        )
        try:
            factory = (
                container.durable_workflow_service._context_service_resolver.factory
            )
            self.assertEqual(factory.generation_mode, "production")
            self.assertIsInstance(
                factory.finding_generator, LLMQuantitativeFindingGenerator
            )
            self.assertIsInstance(
                factory.insight_generator, LLMQuantitativeInsightGenerator
            )
            self.assertIsInstance(
                factory.report_generator, LLMQuantitativeReportGenerator
            )
            self.assertEqual(client.calls, [])
        finally:
            container.shutdown()


if __name__ == "__main__":
    unittest.main()
