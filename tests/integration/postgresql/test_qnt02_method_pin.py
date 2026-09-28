"""QNT-02's opt-in method identity is durable in the real PostgreSQL repository."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from sqlalchemy import text

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.methods.quantitative.pin import METHOD_PIN, ANALYSIS_PIN, resolve_method_pin
from application.quantitative.workflow import CMF_QUANTITATIVE_WORKFLOW_ID
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.one_way_statistics import OneWayStatisticsService
from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.weighting import WeightImportService, approve_weight_set, build_analytical_view
from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.analysis import StatisticalResult, NumericAnalysisSpecification, AnalysisSpecification
from domain.quantitative.dataset import DatasetVersion, DatasetFormat, VariableType, VariableRole
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    create_test_engine,
    integration_tests_enabled,
    postgresql_application_config,
    reset_schema,
)
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import xlsx_bytes
from tests.application.quantitative.test_q2_13a_temp_durable_outcomes import _populate_fixture, SyntheticClient
from tests.api.auth_helpers import auth_headers
from tests.api.helpers import AuthenticatedTestClient, open_test_client, close_test_client


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL test database required")
class Qnt02PostgresqlMethodPinTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_test_engine()
        self.addCleanup(engine.dispose)
        reset_schema(engine)
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def _container(self):
        config = replace(
            postgresql_application_config(
                deterministic_stage_executors=True, background_execution_mode="external"
            ),
            projects_root=self.root.name,
            cmf_quant_enabled=True,
        )
        container = create_application_container(
            config=config,
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
        )
        self.addCleanup(container.shutdown)
        return container

    def test_new_opt_in_quant_method_pin_survives_container_recreation(self) -> None:
        first = self._container()
        study = first.quantitative_ui_service.create_study(
            owner_id="qnt02-owner", title="Synthetic QNT-02", description="Offline fixture",
            submission_key="qnt02-method-pin",
        )
        first_run = first.workflow_service.get_workflow_run(study.run_id)
        self.assertEqual(first_run.workflow_template_id, CMF_QUANTITATIVE_WORKFLOW_ID)
        first_pin = first.workflow_service.get_task_results(study.run_id)[METHOD_PIN]
        self.assertEqual(
            resolve_method_pin(first_pin, project_id=study.project_id, run_id=study.run_id).identity.version,
            "1",
        )
        first.shutdown()

        restarted = self._container()
        self.assertEqual(restarted.workflow_service.get_task_results(study.run_id)[METHOD_PIN], first_pin)
        self.assertEqual(restarted.workflow_service.get_workflow_run(study.run_id).workflow_template_id,
                         CMF_QUANTITATIVE_WORKFLOW_ID)
        changed = deepcopy(first_pin)
        changed["identity"]["version"] = "2"
        with self.assertRaises(ValueError):
            restarted.workflow_service.save_workflow_run(
                restarted.workflow_service.get_workflow_run(study.run_id),
                expected_version=restarted.workflow_service.get_workflow_run_version(study.run_id),
                task_results={METHOD_PIN: changed}, quant_pin_binding={METHOD_PIN: changed},
            )
        self.assertEqual(restarted.workflow_service.get_task_results(study.run_id)[METHOD_PIN], first_pin)

    def test_new_quant_run_persists_exact_imported_dataset_authority(self) -> None:
        container = self._container()
        study = container.quantitative_ui_service.create_study(
            owner_id="qnt02-owner", title="Synthetic dataset", description="Offline fixture",
            submission_key="qnt02-dataset-authority",
        )
        imported_study = container.quantitative_ui_service.upload(
            study.study_id, owner_id="qnt02-owner", filename="synthetic.xlsx",
            content=xlsx_bytes(["score"], [[1], [2], [3]]),
        )
        dataset = container.quantitative_ui_service.state.load(
            imported_study.dataset_record_id, project_id=study.project_id,
            expected_type=DatasetVersion,
        )
        self.assertEqual(dataset.row_count, 3)
        self.assertEqual(dataset.variable_count, 1)
        self.assertTrue(dataset.file_checksum)
        self.assertTrue(dataset.dataset_fingerprint)
        container.shutdown()
        restarted = self._container()
        restored = restarted.quantitative_ui_service.get(study.study_id, owner_id="qnt02-owner")
        self.assertEqual(restored.dataset_record_id, imported_study.dataset_record_id)
        self.assertEqual(restarted.workflow_service.get_task_results(study.run_id)[METHOD_PIN]["identity"]["version"], "1")

    def test_real_postgresql_quant_analysis_stops_before_semantic_generation(self) -> None:
        root = Path(self.root.name)
        config = replace(
            postgresql_application_config(
                deterministic_stage_executors=False, background_execution_mode="external"
            ),
            projects_root=str(root / "protected"), cmf_quant_enabled=True,
        )
        semantic = SyntheticClient("COMPLETED_WITH_NO_SUPPORTED_FINDINGS")
        app = create_application_container(
            config=config, overrides=ApplicationOverrides(llm_client=Mock(), quantitative_llm_client=semantic),
        )
        self.addCleanup(app.shutdown)
        fixture = _populate_fixture(app, root, "qnt02-pg-real-analysis", config,
                                    "COMPLETED_WITH_NO_SUPPORTED_FINDINGS", self, prepare=True)
        run_id = fixture["run_id"]
        results = app.workflow_service.get_task_results(run_id)
        self.assertEqual(results[METHOD_PIN]["identity"]["version"], "1")
        self.assertIn(ANALYSIS_PIN, results)
        self.assertEqual(semantic.calls, [])
        self.assertTrue(fixture["evidence"])

    def test_separate_worker_executes_persisted_quant_without_semantic_calls(self) -> None:
        root = Path(self.root.name)
        config = replace(
            postgresql_application_config(
                deterministic_stage_executors=False, background_execution_mode="external"
            ), projects_root=str(root / "protected"), cmf_quant_enabled=True,
        )
        api_semantic = SyntheticClient("COMPLETED_WITH_NO_SUPPORTED_FINDINGS")
        api = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=Mock(), quantitative_llm_client=api_semantic))
        self.addCleanup(api.shutdown)
        plaintext, key_id, key_prefix, key_hash = api.authentication_service.generate_key_material()
        api.authentication_service.register_api_key(
            name="qnt02-synthetic", key_id=key_id, key_prefix=key_prefix, key_hash=key_hash,
            principal_id="q2-13a-benchmark-owner",
        )
        api._test_api_key_plaintext = plaintext  # Existing server-side UI test credential path.
        raw_client, _, context = open_test_client(api)
        self.addCleanup(lambda: close_test_client(context, api))
        client = AuthenticatedTestClient(raw_client, auth_headers(plaintext))
        created = client.post("/ui/quantitative/studies", data={
            "title": "Synthetic QNT-02 via API", "description": "Offline fixture",
            "submission_key": "qnt02-pg-worker",
        }, follow_redirects=False)
        self.assertEqual(created.status_code, 303, created.text)
        study_id = created.headers["location"].split("/")[-1]
        sav = (Path(__file__).parents[2] / "fixtures/quantitative/rb_reconciliation.sav").read_bytes()
        uploaded = client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": ("synthetic.sav", sav, "application/octet-stream")},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303, uploaded.text)
        existing_study = api.quantitative_ui_service.get(
            study_id, owner_id="q2-13a-benchmark-owner")
        fixture = _populate_fixture(api, root, "qnt02-pg-worker", config,
                                    "COMPLETED_WITH_NO_SUPPORTED_FINDINGS", self,
                                    prepare="activate_only", existing_study=existing_study)
        run_id, project_id = fixture["run_id"], fixture["project_id"]
        ui = api.quantitative_ui_service
        study = ui.get(fixture["study_id"], owner_id="q2-13a-benchmark-owner")
        original, _ = ui._dataset(study)
        replacement = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),),
            storage=ui.storage_factory(project_id, run_id), digest_provider=ui.digest,
        ).import_bytes(
            xlsx_bytes(["score"], [[4], [5], [6]]), filename="newer.xlsx",
            dataset_format=DatasetFormat.XLSX, dataset_id=original.dataset_id,
            project_id=project_id, run_id=run_id, data_sheet="Data", parent_dataset=original,
        )
        self.assertNotEqual(replacement.dataset_version.version_id, original.version_id)
        ui.state.persist(replacement.dataset_version, record_id="qnt02-newer-dataset",
                         project_id=project_id, run_id=run_id,
                         dataset_version_id=replacement.dataset_version.version_id)
        worker_semantic = SyntheticClient("COMPLETED_WITH_NO_SUPPORTED_FINDINGS")
        worker = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=Mock(), quantitative_llm_client=worker_semantic))
        self.addCleanup(worker.shutdown)
        self.assertTrue(worker.worker_execution_service.process_once("qnt02-offline-worker"))
        task_results = worker.workflow_service.get_task_results(run_id)
        self.assertIn(METHOD_PIN, task_results)
        self.assertIn(ANALYSIS_PIN, task_results)
        self.assertEqual(task_results[ANALYSIS_PIN]["authority"]["dataset_version_id"], fixture["dataset_version_id"])
        self.assertEqual(task_results[ANALYSIS_PIN]["authority"]["analysis_plan_version_id"], fixture["plan_version_id"])
        self.assertEqual(task_results[ANALYSIS_PIN]["authority"]["study_weighting_mode"], "UNWEIGHTED")
        self.assertNotIn("_research_kernel_v1", task_results)
        statistics = worker.quantitative_ui_service.state.list_for_run(
            run_id, project_id=project_id, expected_type=StatisticalResult)
        self.assertTrue(statistics)
        self.assertTrue(all(result.dataset_version_id == fixture["dataset_version_id"] for result in statistics))
        self.assertNotIn(replacement.dataset_version.version_id,
                         {result.dataset_version_id for result in statistics})
        snapshots = [item.get("shared_state", {}).get("quantitative", {})
                     for item in task_results.values() if isinstance(item, dict)]
        self.assertTrue(any(item.get("analysis_execution_manifest_record_id") for item in snapshots))
        self.assertTrue(any(item.get("analysis_plan_fingerprint") == fixture["plan_fingerprint"]
                            for item in snapshots))
        original_pin = task_results[ANALYSIS_PIN]
        for field in ("dataset_version_id", "analysis_plan_fingerprint"):
            changed = deepcopy(original_pin)
            changed["authority"][field] = "substituted"
            safe = next(item for item in snapshots if item.get("analysis_plan_fingerprint"))
            with self.assertRaises(ValueError):
                worker.workflow_service.save_workflow_run(
                    worker.workflow_service.get_workflow_run(run_id),
                    expected_version=worker.workflow_service.get_workflow_run_version(run_id),
                    task_results={**task_results, "quantitative": {**safe, field: "substituted"}},
                    quant_pin_binding={ANALYSIS_PIN: changed},
                )
        self.assertEqual(worker.workflow_service.get_task_results(run_id)[ANALYSIS_PIN], original_pin)
        with create_test_engine().connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM evidence WHERE workflow_run_id=:run"),
                                               {"run": run_id}), 0)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM sources WHERE project_id=:project"),
                                               {"project": project_id}), 0)
        self.assertEqual(api_semantic.calls, [])
        self.assertEqual(worker_semantic.calls, [])
        status = client.get(f"/ui/quantitative/studies/{study_id}/status.json")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["run_id"], run_id)

    def test_material_statistical_provenance_survives_postgresql_reload(self) -> None:
        app = self._container()
        study = app.quantitative_ui_service.create_study(
            owner_id="qnt02-owner", title="Provenance", description="Offline fixture",
            submission_key="qnt02-provenance",
        )
        ui = app.quantitative_ui_service
        storage = ui.storage_factory(study.project_id, study.run_id)
        digest = Sha256DigestProvider()
        importer = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),), storage=storage, digest_provider=digest)
        rows = [["r1", 10, 30, "A", 1], ["r2", 20, 40, "A", 3],
                ["r3", 30, 50, "B", 2], ["r4", 40, 60, "B", 4]]
        headers = ["id", "score", "score2", "group", "weight"]
        overrides = {"id": VariableOverride(role=VariableRole.TECHNICAL_ID),
                     "score": VariableOverride(variable_type=VariableType.NUMERIC),
                     "score2": VariableOverride(variable_type=VariableType.NUMERIC),
                     "group": VariableOverride(variable_type=VariableType.CATEGORICAL),
                     "weight": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.WEIGHT)}
        def import_rows(data, parent=None):
            return importer.import_bytes(
                xlsx_bytes(headers, data), filename="provenance.xlsx", dataset_format=DatasetFormat.XLSX,
                dataset_id="qnt02-provenance-data", project_id=study.project_id, run_id=study.run_id,
                data_sheet="Data", overrides=overrides, parent_dataset=parent)
        initial = import_rows(rows)
        newer = import_rows([*rows[:-1], ["r4", 41, 60, "B", 4]], initial.dataset_version)
        for index, imported in enumerate((initial, newer)):
            ui.state.persist(imported.dataset_version, record_id=f"qnt02-prov-dataset-{index}",
                             project_id=study.project_id, run_id=study.run_id,
                             dataset_version_id=imported.dataset_version.version_id)
            ui.state.persist(imported.codebook, record_id=f"qnt02-prov-codebook-{index}",
                             project_id=study.project_id, run_id=study.run_id,
                             dataset_version_id=imported.dataset_version.version_id)

        numeric = NumericStatisticsService(storage=storage, digest_provider=digest)
        def variable_id(codebook, name):
            return next(item.variable_id for item in codebook.variables if item.name == name)
        def result(imported, variable="score", group=None, weighted=False):
            dataset, codebook = imported.dataset_version, imported.codebook
            vid = variable_id(codebook, variable)
            group_id = variable_id(codebook, "group")
            definition = (CrossTabStatisticsService.filter_definition(group_id, group)
                          if group is not None else "ALL_ROWS")
            spec = NumericAnalysisSpecification(
                "qnt02-numeric", vid, weighting_status="WEIGHTED" if weighted else "UNWEIGHTED",
                filter_definition=definition,
                filter_variable_id=group_id if group is not None else None,
                filter_category_value=group,
            )
            refs = numeric.eligible_respondent_refs(dataset=dataset, codebook=codebook,
                                                    specification=spec)
            qc = DatasetQualityAssessment(dataset.version_id, dataset.dataset_fingerprint,
                                          "qnt02-qc", DatasetQualityState.QC_APPROVED,
                                          "qnt02-approved", True, "qnt02-quality")
            weights = None
            approval = None
            if weighted:
                weights = WeightImportService(storage=storage, digest_provider=digest).from_embedded_variable(
                    dataset=dataset, codebook=codebook,
                    variable_id=variable_id(codebook, "weight"))
                approval = approve_weight_set(weight_set=weights, approver_id="qnt02-owner",
                                              approved_at="2026-01-01T00:00:00Z", digest_provider=digest)
            view = build_analytical_view(
                dataset=dataset, quality=qc, specification=spec,
                mode=WeightingMode.WEIGHTED if weighted else WeightingMode.UNWEIGHTED,
                respondent_refs=refs, digest_provider=digest, weight_set=weights,
                approval=approval)
            values = numeric.compute(dataset=dataset, codebook=codebook,
                                     specification=spec, view=view, weight_set=weights)
            return next(item for item in values if item.statistic_type ==
                        ("NUMERIC_WEIGHTED_MEAN" if weighted else "NUMERIC_MEAN"))

        variants = {
            "base": result(initial),
            "dataset": result(newer),
            "variable": result(initial, variable="score2"),
            "filter": result(initial, group="A"),
            "weight": result(initial, weighted=True),
        }
        self.assertEqual(result(initial).reproducibility_fingerprint,
                         variants["base"].reproducibility_fingerprint)
        one_way = OneWayStatisticsService(storage=storage, digest_provider=digest)
        score_id = variable_id(initial.codebook, "score")
        for label, threshold in (("procedure", "1"), ("parameter", "2")):
            spec = AnalysisSpecification("qnt02-one-way", score_id,
                                         presentation_threshold_percent=Decimal(threshold))
            values = one_way.compute(dataset=initial.dataset_version, codebook=initial.codebook,
                                     specification=spec)
            variants[label] = next(item for item in values if item.statistic_type == "MEAN")
        fingerprints = {label: value.reproducibility_fingerprint for label, value in variants.items()}
        self.assertEqual(len(set(fingerprints.values())), len(fingerprints))
        for label, value in variants.items():
            record_id = f"qnt02-prov-result-{label}"
            ui.state.persist(value, record_id=record_id, project_id=study.project_id,
                             run_id=study.run_id, dataset_version_id=value.dataset_version_id)
        app.shutdown()
        reopened = self._container()
        for label, value in variants.items():
            restored = reopened.quantitative_ui_service.state.load(
                f"qnt02-prov-result-{label}", project_id=study.project_id,
                expected_type=StatisticalResult)
            self.assertEqual(restored.reproducibility_fingerprint, fingerprints[label])
            self.assertEqual(restored.dataset_version_id, value.dataset_version_id)
            expected_index = 1 if label == "dataset" else 0
            authority = reopened.quantitative_ui_service.state.load(
                f"qnt02-prov-dataset-{expected_index}", project_id=study.project_id,
                expected_type=DatasetVersion)
            self.assertEqual(restored.dataset_fingerprint, authority.dataset_fingerprint)
            self.assertEqual(restored.data_fingerprint, authority.data_fingerprint)
            self.assertTrue(authority.file_checksum)


if __name__ == "__main__":
    unittest.main()
