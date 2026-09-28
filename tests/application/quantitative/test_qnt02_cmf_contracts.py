from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from application.methods.catalog import production_methods
from application.methods.quantitative.pin import (
    ANALYSIS_PIN, METHOD_PIN, make_analysis_pin, make_method_pin,
    resolve_method_pin, verify_analysis_pin,
)
from application.methods.registry import MethodResolutionError
from application.quantitative.workflow import (
    CMF_QUANTITATIVE_WORKFLOW_ID, QUANTITATIVE_WORKFLOW_ID,
    QUANTITATIVE_SAFE_STATE_KEY, QUANTITATIVE_STAGE_SERVICE_KEY,
    QuantitativeStageExecutor, QuantitativeWorkflowError, build_quantitative_workflow_template,
)
from domain.quantitative.dataset import DatasetFormat
from infrastructure.persistence.postgresql.kernel_ownership import checkpoint_results
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.stage_service_factory import QuantitativeWorkflowContextServiceResolver
from application.quantitative.fingerprints import fingerprint_analysis_specification
from application.quantitative.one_way_statistics import OneWayStatisticsService
from application.methods.quantitative.result_contract import project_result
from application.methods.quantitative.readiness import QuantReadinessState
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import ValidationStatus
from domain.workflow_status import WorkflowStatus
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes
from tests.api.helpers import ApiTestCase
from application.quantitative.comparison_statistics import PROPORTION_METHOD, MEAN_METHOD


class Qnt02CmfContractsTests(unittest.TestCase):
    def _authority(self):
        service = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),), storage=InMemoryDatasetStorage(),
            digest_provider=Sha256DigestProvider(),
        )
        return service.import_bytes(
            xlsx_bytes(["score"], [[1], [2], [3]]), filename="fixture.xlsx",
            dataset_format=DatasetFormat.XLSX, dataset_id="dataset", project_id="project",
            run_id="run", data_sheet="Data",
        )

    def test_quant_registration_is_exact_and_has_no_ark_adapter(self):
        methods = production_methods()
        self.assertEqual(methods.resolve("DESK", "1").capabilities.research_mode, "adaptive_external")
        quant = methods.resolve("QUANTITATIVE", "1")
        self.assertEqual(quant.capabilities.research_mode, "persisted_dataset")
        self.assertFalse(hasattr(quant, "research_adapter"))
        self.assertFalse(hasattr(quant, "research_needs"))
        with self.assertRaises(MethodResolutionError):
            methods.resolve("QUANTITATIVE", "2")

    def test_method_pin_precedes_dataset_and_unknown_version_fails_closed(self):
        pin = make_method_pin(project_id="project", run_id="run")
        self.assertNotIn("dataset", pin)
        self.assertEqual(resolve_method_pin(pin, project_id="project", run_id="run").identity.version, "1")
        changed = deepcopy(pin)
        changed["identity"]["version"] = "2"
        with self.assertRaises((ValueError, MethodResolutionError)):
            resolve_method_pin(changed, project_id="project", run_id="run")
        with self.assertRaises(ValueError):
            resolve_method_pin(pin, project_id="foreign", run_id="run")

    def test_immutable_analysis_authority_rejects_newer_dataset_or_plan(self):
        imported = self._authority()
        dataset, codebook = imported.dataset_version, imported.codebook
        pin = make_method_pin(project_id="project", run_id="run")
        state = {"dataset_record_id": "dataset-record", "codebook_record_id": "codebook-record",
                 "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION", "analysis_plan_version_id": "plan-1",
                 "analysis_plan_fingerprint": "plan-fp", "study_weighting_mode": "UNWEIGHTED"}
        bound = make_analysis_pin(method_pin=pin, project_id="project", run_id="run",
                                  dataset=dataset, codebook=codebook, state=state)
        verify_analysis_pin(bound, method_pin=pin, project_id="project", run_id="run",
                            dataset=dataset, codebook=codebook, state=state)
        with self.assertRaises(ValueError):
            verify_analysis_pin(bound, method_pin=pin, project_id="project", run_id="run",
                                dataset=replace(dataset, version_id="newer"), codebook=codebook, state=state)
        with self.assertRaises(ValueError):
            verify_analysis_pin(bound, method_pin=pin, project_id="project", run_id="run",
                                dataset=dataset, codebook=codebook,
                                state={**state, "analysis_plan_fingerprint": "newer"})
        self.assertEqual(
            checkpoint_results({METHOD_PIN: pin, ANALYSIS_PIN: bound}, {METHOD_PIN: {}, ANALYSIS_PIN: {}}),
            {METHOD_PIN: pin, ANALYSIS_PIN: bound},
        )

    def test_new_template_identity_does_not_reclassify_legacy(self):
        self.assertEqual(build_quantitative_workflow_template().id, QUANTITATIVE_WORKFLOW_ID)
        self.assertEqual(build_quantitative_workflow_template(cmf=True).id, CMF_QUANTITATIVE_WORKFLOW_ID)

    def test_known_answer_result_projection_and_readiness_distinctions(self):
        imported = self._authority()
        dataset, codebook = imported.dataset_version, imported.codebook
        variable = codebook.variables[0]
        spec = AnalysisSpecification("score-summary", variable.variable_id)
        spec = replace(spec, fingerprint=fingerprint_analysis_specification(
            spec, digest_provider=Sha256DigestProvider()))
        storage = InMemoryDatasetStorage()
        # Recreate the immutable parsed snapshot in this isolated test storage.
        storage.put_parsed_rows(dataset.version_id, ((1,), (2,), (3,)))
        results = OneWayStatisticsService(storage=storage, digest_provider=Sha256DigestProvider()).compute(
            dataset=dataset, codebook=codebook, specification=spec)
        mean = next(item for item in results if item.statistic_type == "MEAN")
        self.assertEqual(str(mean.value), "2")
        method_pin = make_method_pin(project_id="project", run_id="run")
        state = {"dataset_record_id": "dataset-record", "codebook_record_id": "codebook-record",
                 "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION", "analysis_plan_version_id": "plan-1",
                 "analysis_plan_fingerprint": "plan-fp", "study_weighting_mode": "UNWEIGHTED"}
        analysis_pin = make_analysis_pin(method_pin=method_pin, project_id="project", run_id="run",
                                         dataset=dataset, codebook=codebook, state=state)
        projected = project_result(method_pin=method_pin, analysis_pin=analysis_pin,
                                   dataset=dataset, codebook=codebook, specification=spec,
                                   result=mean)
        self.assertEqual(projected.outputs["value"]["value"], "2")
        self.assertEqual(projected.source_n, 3)
        self.assertEqual(projected.uncertainty_capability, "NOT_PRODUCED")
        self.assertEqual(project_result(method_pin=method_pin, analysis_pin=analysis_pin,
                                        dataset=dataset, codebook=codebook,
                                        specification=spec, result=mean).provenance_fingerprint,
                         projected.provenance_fingerprint)
        with self.assertRaises(ValueError):
            project_result(method_pin=method_pin, analysis_pin=analysis_pin,
                           dataset=replace(dataset, version_id="changed"), codebook=codebook,
                           specification=spec, result=mean)
        quant = production_methods().resolve("QUANTITATIVE", "1")
        self.assertEqual(quant.assess_readiness(dataset=dataset, codebook=codebook,
                                                procedure="ONE_WAY", eligible_n=3).state,
                         QuantReadinessState.READY)
        self.assertEqual(quant.assess_readiness(dataset=dataset, codebook=codebook,
                                                procedure="ONE_WAY", eligible_n=0).state,
                         QuantReadinessState.INSUFFICIENT_DATA)
        self.assertEqual(quant.assess_readiness(dataset=dataset, codebook=codebook,
                                                procedure="CORRELATION", eligible_n=3).state,
                         QuantReadinessState.UNSUPPORTED_PROCEDURE)
        self.assertEqual(quant.assess_readiness(dataset=dataset, codebook=codebook,
                                                procedure="ONE_WAY", eligible_n=None).state,
                         QuantReadinessState.COMPUTATION_FAILURE)
        self.assertEqual(quant.assess_readiness(dataset=replace(dataset, validation_status=ValidationStatus.BLOCKED),
                                                codebook=codebook, procedure="ONE_WAY", eligible_n=3).state,
                         QuantReadinessState.INVALID_DATASET)

    def test_both_existing_comparisons_project_p_value_without_fake_ci(self):
        from tests.application.quantitative.test_property_qg_deterministic_comparison_provenance import (
            PropertyQGDeterministicComparisonProvenanceTests,
        )
        fixture = PropertyQGDeterministicComparisonProvenanceTests()
        fixture.setUp()
        dataset, codebook = fixture.imported.dataset_version, fixture.imported.codebook
        method_pin = make_method_pin(project_id="p", run_id="r")
        state = {"dataset_record_id": "dataset-record", "codebook_record_id": "codebook-record",
                 "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION", "analysis_plan_version_id": "plan-1",
                 "analysis_plan_fingerprint": "plan-fp", "study_weighting_mode": "UNWEIGHTED"}
        analysis_pin = make_analysis_pin(method_pin=method_pin, project_id="p", run_id="r",
                                         dataset=dataset, codebook=codebook, state=state)
        proportions_a, proportions_b, view = fixture.proportion_inputs()
        proportion_spec = fixture.spec(PROPORTION_METHOD, "response_sig")
        proportion = fixture.compare.compare_proportions(
            dataset=dataset, codebook=codebook, specification=proportion_spec,
            group_a_result=proportions_a, group_b_result=proportions_b, view=view)
        means_a, means_b, view_a, view_b = fixture.mean_inputs()
        mean_spec = fixture.spec(MEAN_METHOD, "score_sig")
        mean = fixture.compare.compare_means(
            dataset=dataset, codebook=codebook, specification=mean_spec,
            group_a_result=means_a, group_b_result=means_b, view_a=view_a, view_b=view_b)
        for specification, result in ((proportion_spec, proportion), (mean_spec, mean)):
            projected = project_result(method_pin=method_pin, analysis_pin=analysis_pin,
                                       dataset=dataset, codebook=codebook,
                                       specification=replace(specification, fingerprint=result.specification_fingerprint),
                                       result=result)
            self.assertEqual(projected.uncertainty_capability, "P_VALUE_ONLY_NO_CI")
            self.assertIsNotNone(projected.p_value)
            self.assertEqual(projected.weighting_status, "UNWEIGHTED")
            self.assertEqual(projected.source_n, 40)
            with self.assertRaises(ValueError):
                project_result(method_pin=method_pin, analysis_pin=analysis_pin,
                               dataset=dataset, codebook=codebook,
                               specification=replace(specification, alpha=specification.alpha / 2,
                                                     fingerprint=result.specification_fingerprint),
                               result=result)

    def test_quant_stage_delegates_without_ark_and_missing_pin_fails_closed(self):
        imported = self._authority()
        dataset, codebook = imported.dataset_version, imported.codebook
        method_pin = make_method_pin(project_id="project", run_id="run")
        state = {"dataset_record_id": "dataset-record", "codebook_record_id": "codebook-record",
                 "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION", "analysis_plan_version_id": "plan-1",
                 "analysis_plan_fingerprint": "plan-fp", "study_weighting_mode": "UNWEIGHTED"}
        analysis_pin = make_analysis_pin(method_pin=method_pin, project_id="project", run_id="run",
                                         dataset=dataset, codebook=codebook, state=state)
        service = Mock()
        service.execute_stage.return_value = state
        context = SimpleNamespace(
            current_task=SimpleNamespace(definition_id="quant_analysis"),
            services={QUANTITATIVE_STAGE_SERVICE_KEY: service},
            shared_state={QUANTITATIVE_SAFE_STATE_KEY: dict(state)},
            execution_metadata={METHOD_PIN: method_pin, ANALYSIS_PIN: analysis_pin},
            project=SimpleNamespace(id="project"),
            workflow_run=SimpleNamespace(id="run", workflow_template_id=CMF_QUANTITATIVE_WORKFLOW_ID),
        )
        self.assertIs(QuantitativeStageExecutor().run(context), context)
        service.execute_stage.assert_called_once()
        context.execution_metadata[METHOD_PIN] = None
        with self.assertRaises(QuantitativeWorkflowError):
            QuantitativeStageExecutor().run(context)

    def test_restart_resolver_rechecks_same_pinned_dataset_and_plan(self):
        imported = self._authority()
        dataset, codebook = imported.dataset_version, imported.codebook
        method_pin = make_method_pin(project_id="project", run_id="run")
        state = {"dataset_record_id": "dataset-record", "codebook_record_id": "codebook-record",
                 "dataset_version_id": dataset.version_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION", "analysis_plan_version_id": "plan-1",
                 "analysis_plan_fingerprint": "plan-fp", "study_weighting_mode": "UNWEIGHTED"}
        analysis_pin = make_analysis_pin(method_pin=method_pin, project_id="project", run_id="run",
                                         dataset=dataset, codebook=codebook, state=state)
        factory = Mock()
        factory._load_dataset_authority.return_value = (dataset, codebook)
        factory.create.return_value = object()
        context = SimpleNamespace(
            workflow_run=SimpleNamespace(id="run", workflow_template_id=CMF_QUANTITATIVE_WORKFLOW_ID,
                                         status=WorkflowStatus.RUNNING),
            project=SimpleNamespace(id="project"),
            shared_state={QUANTITATIVE_SAFE_STATE_KEY: dict(state)},
            execution_metadata={METHOD_PIN: method_pin, ANALYSIS_PIN: analysis_pin},
        )
        self.assertIn(QUANTITATIVE_STAGE_SERVICE_KEY,
                      QuantitativeWorkflowContextServiceResolver(factory).resolve(context))
        factory.create.assert_called_once()
        context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]["analysis_plan_fingerprint"] = "new-plan"
        with self.assertRaises(ValueError):
            QuantitativeWorkflowContextServiceResolver(factory).resolve(context)
        context.shared_state[QUANTITATIVE_SAFE_STATE_KEY] = dict(state)
        factory._load_dataset_authority.return_value = (replace(dataset, version_id="newer"), codebook)
        with self.assertRaises(ValueError):
            QuantitativeWorkflowContextServiceResolver(factory).resolve(context)


class Qnt02CmfCreationTests(ApiTestCase):
    def test_new_opted_in_study_pins_method_before_dataset_upload(self):
        self.container.quantitative_ui_service.cmf_quant_enabled = True
        response = self.client.post("/ui/quantitative/studies", data={
            "title": "Synthetic CMF Quant", "description": "offline contract",
            "submission_key": "qnt02-method-pin",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        study_id = response.headers["location"].rsplit("/", 1)[-1]
        run = self.container.workflow_service.get_workflow_run(study_id)
        self.assertEqual(run.workflow_template_id, CMF_QUANTITATIVE_WORKFLOW_ID)
        results = self.container.workflow_service.get_task_results(study_id)
        self.assertNotIn(ANALYSIS_PIN, results)
        self.assertEqual(resolve_method_pin(results[METHOD_PIN], project_id=study_id,
                                            run_id=study_id).identity.method_id, "QUANTITATIVE")

    def test_analysis_binding_is_persisted_once_and_rejects_changed_plan(self):
        self.container.quantitative_ui_service.cmf_quant_enabled = True
        created = self.client.post("/ui/quantitative/studies", data={
            "title": "Synthetic binding", "description": "offline contract",
            "submission_key": "qnt02-analysis-pin",
        }, follow_redirects=False)
        self.assertEqual(created.status_code, 303)
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        uploaded = self.client.post(f"/ui/quantitative/studies/{study_id}/dataset",
                                    files={"dataset": ("fixture.xlsx", xlsx_bytes(["score"], [[1], [2], [3]]),
                                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                                    follow_redirects=False)
        self.assertEqual(uploaded.status_code, 303)
        ui = self.container.quantitative_ui_service
        principal = self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext).principal_id
        study = ui.get(study_id, owner_id=principal)
        dataset, _ = ui._dataset(study)
        run = self.container.workflow_service.get_workflow_run(study_id)
        state = {"dataset_record_id": study.dataset_record_id,
                 "codebook_record_id": study.codebook_record_id,
                 "dataset_version_id": dataset.version_id,
                 "dataset_fingerprint": dataset.dataset_fingerprint,
                 "qc_record_id": "qc-record", "qc_fingerprint": "qc-fp", "qc_approval_id": "qc-approval",
                 "analysis_execution_mode": "DESIGN_AWARE_EXECUTION",
                 "analysis_plan_version_id": "plan-1", "analysis_plan_fingerprint": "plan-fp",
                 "study_weighting_mode": "UNWEIGHTED"}
        ui._persist_activation_state(run, state)
        persisted = self.container.workflow_service.get_task_results(study_id)
        self.assertIn(ANALYSIS_PIN, persisted)
        self.assertEqual(persisted[ANALYSIS_PIN]["authority"]["dataset_version_id"], dataset.version_id)
        with self.assertRaises(ValueError):
            ui._persist_activation_state(run, {**state, "analysis_plan_fingerprint": "changed"})
        self.assertEqual(self.container.workflow_service.get_task_results(study_id)[ANALYSIS_PIN],
                         persisted[ANALYSIS_PIN])
