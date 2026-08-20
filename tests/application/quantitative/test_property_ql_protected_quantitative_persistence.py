from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine, text

from application.ports.quantitative_state_repository import QuantitativeStateRecord
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService, validate_recovered_analysis_linkage, validate_recovered_dataset
from application.quantitative.fingerprints import fingerprint_codebook, fingerprint_data, fingerprint_dataset, fingerprint_schema, sha256_bytes
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult, StatisticalTable
from domain.quantitative.dataset import CodebookVersion, DatasetFormat, DatasetVersion, DatasetVersionKind, PiiClassification, ValidationStatus, VariableDefinition, VariableType
from domain.quantitative.finding import QuantitativeClaim, QuantitativeClaimType, QuantitativeFinding, QuantitativeFindingRejection, QuantitativeResultReference, QuantitativeSupportStatus
from domain.quantitative.insight import QuantitativeFindingReference, QuantitativeInsight, QuantitativeInsightType, QuantitativeInsightValidationStatus
from domain.quantitative.quality import ApprovalState, CleaningDecisionSet
from domain.quantitative.report import QuantitativeReport, QuantitativeReportSection, QuantitativeReportSectionType, QuantitativeReportSupportReference, QuantitativeReportValidationStatus
from domain.quantitative.weighting import WeightSet, WeightSourceType, WeightValidationStatus
from infrastructure.quantitative.storage.protected_file_dataset_storage import ProtectedDatasetCorruptionError, ProtectedFileDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from infrastructure.persistence.postgresql.models.project_model import ProjectModel  # registers FK target
from infrastructure.persistence.postgresql.models.quantitative_state_model import QuantitativeStateModel
from infrastructure.persistence.postgresql.repositories.postgresql_quantitative_state_repository import PostgreSQLQuantitativeStateRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class DurableTestRecordRepository:
    """Shared durable backing simulates repository recreation without process state."""
    def __init__(self, backing): self.backing = backing
    def create(self, record):
        if record.record_id in self.backing: raise ValueError("immutable record")
        self.backing[record.record_id] = record
    def get_for_project(self, record_id, *, project_id):
        value = self.backing.get(record_id)
        return value if value and value.project_id == project_id else None
    def list_for_run(self, run_id, *, project_id, record_type=None):
        return tuple(value for value in self.backing.values() if value.run_id == run_id and value.project_id == project_id and (record_type is None or value.record_type == record_type))


def dataset():
    return DatasetVersion("dataset", "version", "project-a", "run-a", DatasetVersionKind.RAW, "file", "survey.sav", "a" * 64, DatasetFormat.SAV, 2, 3, "schema", "codebook", "codebook-fp", "data-fp", "dataset-fp", PiiClassification.PII_RESTRICTED, ValidationStatus.VALID, "protected-dataset://opaque", "pyreadstat", "1.3.5", respondent_identity_kind="technical_id_pseudonym", weight_set_binding_supported=True)


def statistical_result():
    return StatisticalResult("result", "version", "dataset-fp", "data-fp", "codebook-fp", "var-q1", "var-fp", "spec", "spec-fp", "UNWEIGHTED", "ALL_ROWS", "VALID_RESPONSES", (), "VALID_PERCENTAGE", Decimal("42"), 100, "YES", "deterministic", "v1", True, "result-fp", unweighted_n=2)


class PropertyQLProtectedQuantitativePersistenceTests(unittest.TestCase):
    def setUp(self): self.digest = Sha256DigestProvider()

    def storage(self, root, project="project-a", run="run-a"):
        return ProtectedFileDatasetStorage(root=root, project_id=project, run_id=run, digest_provider=self.digest)

    def test_protected_data_survives_restart_and_paths_are_opaque(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.storage(root)
            manifest = dataset(); raw = b"synthetic-sav-bytes"
            rows = (("Alice Example", "+49 123456789", 1), ("Bob Example", None, 2))
            lineage = ("pseudo-a", "pseudo-b")
            bindings = (("string:raw-a", "pseudo-a"), ("string:raw-b", "pseudo-b"))
            locator = first.put_raw_file("file", raw)
            first.put_parsed_rows("version", rows); first.put_respondent_lineage("version", lineage)
            first.put_protected_respondent_bindings("version", bindings); first.put_manifest(manifest)
            self.assertTrue(locator.startswith("protected-dataset://")); self.assertNotIn(str(Path(root)), locator)
            restarted = self.storage(root)
            self.assertEqual(restarted.get_raw_file("file"), raw)
            self.assertEqual(restarted.get_parsed_rows("version"), rows)
            self.assertEqual(restarted.get_respondent_lineage("version"), lineage)
            self.assertEqual(restarted.get_protected_respondent_bindings("version"), bindings)
            self.assertEqual(restarted.get_manifest("version"), manifest)

    def test_wrong_project_and_run_cannot_read_protected_data(self):
        with tempfile.TemporaryDirectory() as root:
            self.storage(root).put_parsed_rows("version", (("secret",),))
            for other in (self.storage(root, project="project-b"), self.storage(root, run="run-b")):
                with self.assertRaises(ProtectedDatasetCorruptionError): other.get_parsed_rows("version")

    def test_corruption_and_immutable_collision_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            storage = self.storage(root); storage.put_parsed_rows("version", ((1,),))
            with self.assertRaisesRegex(ValueError, "immutable"): storage.put_parsed_rows("version", ((2,),))
            target = next(Path(root).rglob("rows-*.ql")); target.write_text("{}", encoding="utf-8")
            with self.assertRaises(ProtectedDatasetCorruptionError): self.storage(root).get_parsed_rows("version")

    def test_malformed_json_and_wrong_envelope_or_payload_shape_fail_closed(self):
        cases = ("not-json", "[]", '{"version":"ql-1"}')
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as root:
                storage = self.storage(root); storage.put_parsed_rows("version", ((1,),))
                next(Path(root).rglob("rows-*.ql")).write_text(content, encoding="utf-8")
                with self.assertRaises(ProtectedDatasetCorruptionError): storage.get_parsed_rows("version")
        with tempfile.TemporaryDirectory() as root:
            storage = self.storage(root); storage.put_parsed_rows("version", ((1,),))
            malformed = "{bad-payload"
            envelope = {"version": "ql-1", "checksum": sha256_bytes(malformed.encode(), digest_provider=self.digest), "payload": malformed}
            next(Path(root).rglob("rows-*.ql")).write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ProtectedDatasetCorruptionError, "JSON is malformed"): storage.get_parsed_rows("version")

    def test_dataset_fingerprints_are_recomputed_and_linkage_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            storage = self.storage(root); raw = b"survey"; rows = ((1,), (2,))
            variable = VariableDefinition("var", "q1", "Question", VariableType.NUMERIC, fingerprint="variable-fp")
            codebook_fp = fingerprint_codebook((variable,), digest_provider=self.digest)
            codebook = CodebookVersion("codebook", (variable,), codebook_fp)
            file_fp = sha256_bytes(raw, digest_provider=self.digest); schema_fp = fingerprint_schema((variable,), digest_provider=self.digest); data_fp = fingerprint_data(rows, digest_provider=self.digest)
            dataset_fp = fingerprint_dataset(file_checksum=file_fp, schema_fingerprint=schema_fp, codebook_fingerprint=codebook_fp, data_fingerprint=data_fp, digest_provider=self.digest)
            manifest = replace(dataset(), file_checksum=file_fp, schema_fingerprint=schema_fp, codebook_fingerprint=codebook_fp, data_fingerprint=data_fp, dataset_fingerprint=dataset_fp)
            storage.put_raw_file("file", raw); storage.put_parsed_rows("version", rows)
            validate_recovered_dataset(dataset=manifest, codebook=codebook, storage=storage, digest_provider=self.digest)
            with self.assertRaises(QuantitativePersistenceError): validate_recovered_dataset(dataset=replace(manifest, data_fingerprint="tampered"), codebook=codebook, storage=storage, digest_provider=self.digest)
            with self.assertRaisesRegex(QuantitativePersistenceError, "WeightSet"):
                validate_recovered_analysis_linkage(dataset=manifest, weight_set=replace(self._weight_set(), dataset_fingerprint="other"))

    def test_safe_metadata_restart_authorization_and_fingerprint_validation(self):
        backing = {}
        first = QuantitativeStateService(repository=DurableTestRecordRepository(backing), digest_provider=self.digest)
        manifest = dataset(); result = statistical_result()
        first.persist(manifest, record_id="dataset-record", project_id="project-a", run_id="run-a", dataset_version_id="version")
        first.persist(result, record_id="result-record", project_id="project-a", run_id="run-a", dataset_version_id="version", accepted=True)
        serialized = json.dumps([item.payload for item in backing.values()], sort_keys=True)
        self.assertNotIn("Alice", serialized); self.assertNotIn("+49", serialized)
        restarted = QuantitativeStateService(repository=DurableTestRecordRepository(backing), digest_provider=self.digest)
        self.assertEqual(restarted.load("dataset-record", project_id="project-a", expected_type=DatasetVersion), manifest)
        self.assertEqual(restarted.load("result-record", project_id="project-a", expected_type=StatisticalResult), result)
        with self.assertRaises(QuantitativePersistenceError): restarted.load("result-record", project_id="project-b")
        original = backing["result-record"]
        backing["result-record"] = replace(original, authority_fingerprint="tampered")
        with self.assertRaisesRegex(QuantitativePersistenceError, "authority fingerprint"): restarted.load("result-record", project_id="project-a")

    def test_rejected_audit_state_and_lineage_fields_survive(self):
        backing = {}; service = QuantitativeStateService(repository=DurableTestRecordRepository(backing), digest_provider=self.digest)
        result = statistical_result()
        record = service.persist(result, record_id="rejected-proposal-result", project_id="project-a", run_id="run-a", dataset_version_id="version", parent_record_id="generation-1", accepted=False)
        self.assertFalse(record.accepted); self.assertEqual(record.parent_record_id, "generation-1")
        listed = DurableTestRecordRepository(backing).list_for_run("run-a", project_id="project-a")
        self.assertEqual(listed, (record,))

    def test_complete_safe_authority_chain_round_trips(self):
        variable = VariableDefinition("var-q1", "q1", "Question", VariableType.CATEGORICAL, fingerprint="variable-fp")
        codebook = CodebookVersion("codebook", (variable,), "codebook-fp")
        cleaning = CleaningDecisionSet("cleaning", "version", "dataset-fp", (), "preview-fp", 0, ApprovalState.APPROVED, "analyst", "2026-01-01", "cleaning-fp")
        weights = self._weight_set()
        result = statistical_result()
        table = StatisticalTable("table", "spec", "spec-fp", "var-q1", "group", "COLUMN_PERCENTAGE", "UNWEIGHTED", None, "view-fp", "ALL_ROWS", "VALID_RESPONSES", ("result",), (), (), "table-fp")
        comparison = AnalyticalComparisonResult("comparison", "version", "dataset-fp", "data-fp", "comparison-spec", "comparison-spec-fp", "result", "result-fp", "result-b", "result-b-fp", Decimal("12"), Decimal("2.5"), Decimal("0.02"), Decimal("0.05"), True, "TWO_SIDED", 2, 50, 50, "INDEPENDENT_TWO_PROPORTION_Z_TEST", "qg-1", "comparison-fp")
        finding = QuantitativeFinding("finding", "42.0% selected yes.", QuantitativeClaim(QuantitativeClaimType.DESCRIPTIVE_VALUE, Decimal("42"), "var-q1", "VALID_PERCENTAGE", "YES", "ALL_ROWS", "VALID_RESPONSES", "UNWEIGHTED", display_value="42.0"), (QuantitativeResultReference("result", "result-fp"),), analytical_context_fingerprint="context-fp", support_validation_status=QuantitativeSupportStatus.SUPPORTED, support_validation_fingerprint="finding-fp")
        insight = QuantitativeInsight("insight", "The accepted share was 42.0%.", QuantitativeInsightType.SYNTHESIS, (QuantitativeFindingReference("finding", "finding-fp"),), ("42.0",), support_context_fingerprint="context-fp", validation_status=QuantitativeInsightValidationStatus.SUPPORTED, validation_fingerprint="insight-fp")
        section = QuantitativeReportSection("section", QuantitativeReportSectionType.KEY_FINDINGS, "Key findings", "The accepted share was 42.0%.", (QuantitativeReportSupportReference("finding", "finding-fp"),), (QuantitativeReportSupportReference("insight", "insight-fp"),), ("42.0",), ("result",), weighting_status="UNWEIGHTED", filter_definition="ALL_ROWS", base_definition="VALID_RESPONSES")
        report = QuantitativeReport("report", "Survey", (section,), (QuantitativeReportSupportReference("finding", "finding-fp"),), (QuantitativeReportSupportReference("insight", "insight-fp"),), analytical_support_fingerprint="report-support-fp", validation_status=QuantitativeReportValidationStatus.SUPPORTED, validation_fingerprint="report-fp")
        rejection = QuantitativeFindingRejection(1, {"finding_text": "unsupported"}, "deterministic rejection", "rejection-fp")
        values = (codebook, cleaning, weights, result, table, comparison, finding, insight, report, rejection)
        backing = {}; first = QuantitativeStateService(repository=DurableTestRecordRepository(backing), digest_provider=self.digest)
        for index, value in enumerate(values): first.persist(value, record_id=f"record-{index}", project_id="project-a", run_id="run-a", dataset_version_id="version", accepted=True)
        restarted = QuantitativeStateService(repository=DurableTestRecordRepository(backing), digest_provider=self.digest)
        self.assertEqual(tuple(restarted.load(f"record-{index}", project_id="project-a", expected_type=type(value)) for index, value in enumerate(values)), values)
        payload = json.dumps([item.payload for item in backing.values()], sort_keys=True)
        self.assertNotIn("raw-a", payload)  # pseudonyms are allowed; protected raw identities are not

    def test_generic_workflow_artifact_and_log_modules_are_not_dependencies(self):
        source = Path("infrastructure/quantitative/storage/protected_file_dataset_storage.py").read_text(encoding="utf-8") + Path("application/quantitative/state_persistence.py").read_text(encoding="utf-8")
        for forbidden in ("WorkflowContext", "ArtifactRecord", "ExecutionLogEntry", "LLMClient", "domain.evidence"):
            self.assertNotIn(forbidden, source)

    @staticmethod
    def _weight_set():
        return WeightSet("weights", "version", "dataset-fp", WeightSourceType.EMBEDDED_VARIABLE, "source-fp", "keys-fp", (("pseudo-a", Decimal("1.2")), ("pseudo-b", Decimal("0.8"))), "vector-fp", 2, 2, 2, Decimal("1"), Decimal("0.8"), Decimal("1.2"), Decimal("1"), Decimal("2"), 0, 0, 0, 0, 0, 0, WeightValidationStatus.VALID, (), "validation-fp", "weights-fp")

    def test_relational_repository_is_restart_safe_and_project_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'state.db'}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE projects (id VARCHAR(64) PRIMARY KEY)"))
                connection.execute(text("INSERT INTO projects (id) VALUES ('project-a'), ('project-b')"))
            QuantitativeStateModel.__table__.create(engine)
            first = QuantitativeStateService(repository=PostgreSQLQuantitativeStateRepository(DatabaseSessionFactory(engine)), digest_provider=self.digest)
            first.persist(statistical_result(), record_id="result", project_id="project-a", run_id="run-a", dataset_version_id="version")
            engine.dispose()
            restarted_engine = create_engine(f"sqlite:///{Path(root) / 'state.db'}")
            restarted = QuantitativeStateService(repository=PostgreSQLQuantitativeStateRepository(DatabaseSessionFactory(restarted_engine)), digest_provider=self.digest)
            self.assertEqual(restarted.load("result", project_id="project-a"), statistical_result())
            with self.assertRaises(QuantitativePersistenceError): restarted.load("result", project_id="project-b")
            restarted_engine.dispose()


if __name__ == "__main__": unittest.main()
