from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

from sqlalchemy import text

from application.analysis.numeric_integrity import qualify_numeric_information_need
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from application.report.claim_contract import claim_digest_v2
from application.report.claim_lineage_v2 import build_claim_lineage_v2
from application.report.claim_lineage_verification_v2 import (
    ClaimLineageVerificationV2Error,
    verify_persisted_claim_v2_snapshot_consistent_read,
    verify_persisted_claim_v2_snapshot_write_transaction,
    verify_persisted_claim_v2,
)
from domain.factories.project_factory import ProjectFactory
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reports.report_claim import REPORT_CLAIM_V2_VERSION, ClaimScope, NumericFact, ReportClaim, ReportClaimContractError
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.models.evidence_model import EvidenceModel
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import PostgreSQLReportClaimRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import PostgreSQLReportRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import PostgreSQLWorkflowTemplateRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
import tests.application.analysis.test_numeric_integrity as numeric_fixtures
from tests.application.research_quality.test_evidence_completeness_diagnostics import evidence as evidence_fixture
from tests.application.research_quality.test_evidence_completeness_diagnostics import source as source_fixture
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


class PostgreSQLReportClaimV2VerificationTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project = ProjectFactory().create("ReportClaim v2 verification")
        PostgreSQLProjectRepository(self.session_factory).create(self.project)
        self.design = numeric_fixtures.CanonicalNumericQualificationTests().design(periods=("2019",))
        self.brief = ResearchBrief(
            title="Population", business_question="Population in 2019",
            timeframe="as of 31 December 2019",
        )
        self.template = WorkflowTemplate(
            id="v2-template", name="V2 authority", research_design_snapshot=self.design,
            research_brief_snapshot=self.brief,
        )
        self.templates = PostgreSQLWorkflowTemplateRepository(self.session_factory)
        self.templates.save_snapshot(self.template, project_id=self.project.id)
        self.run = WorkflowRun(
            id="run", project_id=self.project.id, workflow_template_id=self.template.id,
        )
        self.runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        self.runs.create(self.run, project_id=self.project.id)

        self.sources = PostgreSQLSourceRepository(self.session_factory)
        source = replace(
            source_fixture(workflow=self.run.id, design=self.design.id),
            project_id=self.project.id, terminal_resource_key="", raw_content_checksum="",
            raw_checksum_kind="legacy-surrogate",
        )
        self.sources.create(source)
        self.source = self.sources.get_by_id(source.id)
        assert self.source is not None
        base_evidence = evidence_fixture(
            self.source, workflow=self.run.id, design=self.design.id,
            subject_id=self.design.research_subject.subject_id,
            subject_fingerprint=self.design.research_subject.semantic_fingerprint,
        )
        self.evidence = replace(
            base_evidence, project_id=self.project.id, research_question_refs=("rq",),
            deduplication_key="v2-evidence",
        )
        self.evidence_repo = PostgreSQLEvidenceRepository(self.session_factory)
        self.evidence_repo.create(self.evidence)
        self.finding = Finding(
            id="finding-v2", project_id=self.project.id, workflow_run_id=self.run.id,
            research_design_id=self.design.id, statement="Population was 100 persons in 2019.",
            rationale="Canonical observation", evidence_refs=(self.evidence.id,),
            created_at="2026-01-01T00:00:00Z", research_question_refs=("rq",),
            information_need_refs=(self.design.information_needs[0].id,),
            finding_type=FindingType.SYNTHESIS, analysis_method="deterministic",
            deduplication_key="v2-finding",
        )
        self.insight = Insight(
            id="insight-v2", project_id=self.project.id, workflow_run_id=self.run.id,
            research_design_id=self.design.id, statement="A baseline is available.",
            implication="The annual value is traceable.", finding_refs=(self.finding.id,),
            created_at="2026-01-01T00:00:00Z", research_question_refs=("rq",),
            deduplication_key="v2-insight",
        )
        self.findings = PostgreSQLFindingRepository(self.session_factory)
        self.insights = PostgreSQLInsightRepository(self.session_factory)
        self.findings.create(self.finding); self.insights.create(self.insight)
        self.scope = ClaimScope(
            ("ukraine",), (), ("2019",), ("population",), (),
            (NumericFact("100", "persons", "absolute", ("ukraine",), ("2019",), ("population",), ()),),
        )
        temporal = qualify_evidence_with_temporal_decisions(
            design=self.design, evidence=(self.evidence,), brief=self.brief,
            source_repository=self.sources,
        )
        qualification = qualify_numeric_information_need(
            design=self.design, information_need=self.design.information_needs[0],
            evidence=(self.evidence,), source_repository=self.sources,
            temporal_decisions=temporal.decisions, allowed_workflow_run_ids=(self.run.id,),
        )
        self.assertTrue(qualification.available)
        self.assertEqual((self.evidence.id,), tuple(item.id for item in qualification.accepted_evidence))
        material = build_claim_lineage_v2(
            project_id=self.project.id, source_workflow_run_id=self.run.id,
            report_workflow_run_id="report-run", design=self.design, scope=self.scope,
            findings=(self.finding,), insights=(self.insight,),
            evidence_by_id={self.evidence.id: self.evidence}, source_by_id={self.source.id: self.source},
            temporal_decisions=temporal.decisions, allowed_workflow_run_ids=(self.run.id,),
            numeric_qualifications={self.design.information_needs[0].id: qualification},
        )
        values = dict(
            claim_id="claim-v2", project_id=self.project.id, source_workflow_run_id=self.run.id,
            report_workflow_run_id="report-run", design_id=self.design.id,
            research_question_ids=("rq",), information_need_ids=(self.design.information_needs[0].id,),
            finding_ids=material.finding_ids, insight_ids=material.insight_ids,
            evidence_ids=material.evidence_ids, kind="observation",
            proposition=self.finding.statement, certainty="direct", direction="not_applicable",
            scope=self.scope, support_evidence_ids=material.evidence_ids,
            source_ids=material.source_ids, citation_ids=("citation-1",),
            finding_content_digests=dict(material.finding_content_digests),
            insight_content_digests=dict(material.insight_content_digests),
            insight_finding_refs=dict(material.insight_finding_refs),
            evidence_content_digests=dict(material.evidence_content_digests),
            source_revision_digests=dict(material.source_revision_digests),
            numeric_observation_proof_digests=dict(material.numeric_observation_proof_digests),
            status="validated", contract_version=REPORT_CLAIM_V2_VERSION,
            authority_digest=material.authority_digest, validated_at="2026-01-01T00:00:00Z",
            version=REPORT_CLAIM_V2_VERSION,
        )
        draft = SimpleNamespace(**values)
        values["claim_digest"] = claim_digest_v2(draft)
        self.claim = ReportClaim(**values)
        self.report = Report(
            id="report-v2", project_id=self.project.id, workflow_run_id="report-run",
            research_design_id=self.design.id, title="Population", language="en", sections=(),
            executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
            generation_method="v2-test", finding_refs=(self.finding.id,),
            insight_refs=(self.insight.id,), evidence_refs=(self.evidence.id,),
            citation_registry={}, deduplication_key="report-v2", revision_number=1,
            metadata={"structured_claim_contract": REPORT_CLAIM_V2_VERSION},
        )
        self.claims = PostgreSQLReportClaimRepository(self.session_factory)
        self.claims.create_with_report(self.report, (self.claim,))

    def verify_fresh(self):
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        reports = PostgreSQLReportRepository(self.session_factory)
        claim = claims.list_for_report(self.report.id, 1)[0]
        report = reports.get_by_id(self.report.id)
        return verify_persisted_claim_v2(
            claim=claim, report=report,
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=PostgreSQLSourceRepository(self.session_factory),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(self.session_factory),
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(self.session_factory),
        )

    def verify_fresh_snapshot(self):
        return self.verify_fresh_snapshot_with_ids(
            report_id=self.report.id,
            claim_id=self.claim.claim_id,
        )

    def verify_fresh_snapshot_with_ids(self, *, report_id, claim_id, report_claim_repository=None):
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        reports = PostgreSQLReportRepository(self.session_factory)
        return verify_persisted_claim_v2_snapshot_consistent_read(
            session_factory=self.session_factory, report_id=report_id, claim_id=claim_id,
            report_repository=reports, report_claim_repository=report_claim_repository or claims,
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=PostgreSQLSourceRepository(self.session_factory),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(self.session_factory),
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(self.session_factory),
        )

    def test_persist_reload_and_independent_authority_verification(self) -> None:
        verified = self.verify_fresh()
        self.assertEqual(self.claim.claim_id, verified.claim_id)
        self.assertEqual(self.claim.authority_digest, verified.authority_digest)

    def test_consistent_read_snapshot_survives_transaction_close(self) -> None:
        snapshot = self.verify_fresh_snapshot()
        self.assertEqual(snapshot.claim.claim_id, self.claim.claim_id)
        self.assertEqual(snapshot.material.authority_digest, self.claim.authority_digest)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE sources SET title='changed-after-read' WHERE id='source-1'"))
        self.assertNotEqual(snapshot.source_by_id["source-1"].title, "changed-after-read")

    def test_consistent_read_rejects_repositories_from_another_factory(self) -> None:
        with self.assertRaises(ClaimLineageVerificationV2Error):
            verify_persisted_claim_v2_snapshot_consistent_read(
                session_factory=self.session_factory, report_id=self.report.id, claim_id=self.claim.claim_id,
                report_repository=PostgreSQLReportRepository(self.session_factory),
                report_claim_repository=PostgreSQLReportClaimRepository(self.session_factory),
                finding_repository=PostgreSQLFindingRepository(self.session_factory),
                insight_repository=PostgreSQLInsightRepository(self.session_factory),
                evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
                source_repository=PostgreSQLSourceRepository(self.session_factory),
                workflow_run_repository=PostgreSQLWorkflowRunRepository(self.session_factory),
                workflow_template_repository=PostgreSQLWorkflowTemplateRepository(
                    type(self.session_factory)(self.engine),
                ),
            )

    def test_consistent_read_rejects_missing_report_and_claim(self) -> None:
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh_snapshot_with_ids(report_id="missing-report", claim_id=self.claim.claim_id)
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh_snapshot_with_ids(report_id=self.report.id, claim_id="missing-claim")

    def test_consistent_read_rejects_mismatched_membership(self) -> None:
        class MismatchedMembershipRepository(PostgreSQLReportClaimRepository):
            def list_for_report(self, report_id, report_revision):
                return []

        claims = MismatchedMembershipRepository(self.session_factory)
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh_snapshot_with_ids(
                report_id=self.report.id, claim_id=self.claim.claim_id,
                report_claim_repository=claims,
            )

    def test_consistent_read_rejects_incompatible_active_transaction(self) -> None:
        with self.assertRaises(ClaimLineageVerificationV2Error):
            with self.session_factory.transaction():
                self.verify_fresh_snapshot()

    def test_write_transaction_verification_locks_and_returns_detached_snapshot(self) -> None:
        repositories = (
            ("report", PostgreSQLReportRepository(self.session_factory)),
            ("claims", self.claims),
            ("findings", self.findings),
            ("insights", self.insights),
            ("evidence", self.evidence_repo),
            ("sources", self.sources),
            ("runs", self.runs),
            ("templates", self.templates),
        )
        for name, repository in repositories:
            with self.subTest(repository=name):
                self.assertIs(getattr(repository, "_session_factory", None), self.session_factory)
        with self.session_factory.repeatable_read_transaction():
            snapshot = verify_persisted_claim_v2_snapshot_write_transaction(
                session_factory=self.session_factory,
                report_id=self.report.id,
                claim_id=self.claim.claim_id,
                report_repository=repositories[0][1],
                report_claim_repository=self.claims,
                finding_repository=self.findings,
                insight_repository=self.insights,
                evidence_repository=self.evidence_repo,
                source_repository=self.sources,
                workflow_run_repository=self.runs,
                workflow_template_repository=self.templates,
            )
        self.assertEqual(snapshot.claim.claim_id, self.claim.claim_id)

    def test_write_transaction_verification_rejects_malformed_ids_and_wrong_transaction(self) -> None:
        repositories = dict(
            session_factory=self.session_factory,
            report_id=self.report.id,
            claim_id=self.claim.claim_id,
            report_repository=PostgreSQLReportRepository(self.session_factory),
            report_claim_repository=self.claims,
            finding_repository=self.findings,
            insight_repository=self.insights,
            evidence_repository=self.evidence_repo,
            source_repository=self.sources,
            workflow_run_repository=self.runs,
            workflow_template_repository=self.templates,
        )
        with self.assertRaises(ClaimLineageVerificationV2Error):
            verify_persisted_claim_v2_snapshot_write_transaction(**repositories)
        original = self.claim

        class MalformedClaim:
            def __init__(self, claim):
                self._claim = claim
                self.claim_id = claim.claim_id
                self.evidence_ids = ("",)

            def __getattr__(self, name):
                return getattr(self._claim, name)

        malformed = MalformedClaim(original)

        class MalformedClaims(type(self.claims)):
            def get_by_id(self, claim_id):
                return malformed

            def list_for_report(self, report_id, report_revision):
                return [malformed]

        repositories["report_claim_repository"] = MalformedClaims(self.session_factory)
        with self.session_factory.repeatable_read_transaction():
            with self.assertRaises(ClaimLineageVerificationV2Error):
                verify_persisted_claim_v2_snapshot_write_transaction(**repositories)

    def test_membership_trigger_rejects_direct_update_and_delete(self) -> None:
        with self.engine.connect() as connection:
            count = connection.execute(text(
                "SELECT COUNT(*) FROM report_revision_claims "
                "WHERE report_id=:report_id AND report_claim_id=:claim_id"
            ), {"report_id": self.report.id, "claim_id": self.claim.claim_id}).scalar_one()
            trigger = connection.execute(text(
                "SELECT tgenabled FROM pg_trigger "
                "WHERE tgrelid='report_revision_claims'::regclass "
                "AND tgname='trg_report_revision_claims_immutable'"
            )).scalar_one_or_none()
        self.assertEqual(count, 1)
        self.assertEqual(trigger, "O")
        with self.assertRaises(Exception):
            with self.engine.begin() as connection:
                try:
                    connection.execute(text(
                    "UPDATE report_revision_claims SET report_revision=2 "
                    "WHERE report_id=:report_id AND report_claim_id=:claim_id"
                    ), {"report_id": self.report.id, "claim_id": self.claim.claim_id})
                except Exception as exc:
                    self.assertIn("report_revision_claims are immutable", str(exc))
                    raise
        with self.assertRaises(Exception):
            with self.engine.begin() as connection:
                try:
                    connection.execute(text(
                    "DELETE FROM report_revision_claims "
                    "WHERE report_id=:report_id AND report_claim_id=:claim_id"
                    ), {"report_id": self.report.id, "claim_id": self.claim.claim_id})
                except Exception as exc:
                    self.assertIn("report_revision_claims are immutable", str(exc))
                    raise

    def test_write_verifier_locks_source_until_commit_then_writer_proceeds(self) -> None:
        entered, attempted, completed, release = Event(), Event(), Event(), Event()
        writer_pid = {}

        def verifier_holder() -> None:
            try:
                with self.session_factory.repeatable_read_transaction():
                    verify_persisted_claim_v2_snapshot_write_transaction(
                        session_factory=self.session_factory,
                        report_id=self.report.id,
                        claim_id=self.claim.claim_id,
                        report_repository=PostgreSQLReportRepository(self.session_factory),
                        report_claim_repository=self.claims,
                        finding_repository=self.findings,
                        insight_repository=self.insights,
                        evidence_repository=self.evidence_repo,
                        source_repository=self.sources,
                        workflow_run_repository=self.runs,
                        workflow_template_repository=self.templates,
                    )
                    entered.set()
                    release.wait(timeout=10)
            finally:
                release.set()

        def source_writer() -> None:
            factory = DatabaseSessionFactory(self.engine)
            repository = PostgreSQLSourceRepository(factory)
            with factory.transaction() as session:
                current = repository.get_by_id(self.source.id)
                session.execute(text("SET LOCAL lock_timeout='5s'"))
                writer_pid["value"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                attempted.set()
                updated = replace(
                    current,
                    metadata={**current.metadata, "discovery_records": ("concurrent",)},
                )
                repository.save(updated, expected_version=current.version)
            completed.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            verifier = pool.submit(verifier_holder)
            self.assertTrue(entered.wait(timeout=10))
            writer = pool.submit(source_writer)
            try:
                self.assertTrue(attempted.wait(timeout=10))
                deadline = time.monotonic() + 10
                blocked = False
                while time.monotonic() < deadline:
                    with self.engine.connect() as connection:
                        blocked = bool(connection.execute(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": writer_pid["value"]},
                        ).scalar_one())
                    if blocked:
                        break
                    self.assertFalse(completed.is_set())
                    time.sleep(0.05)
                self.assertTrue(blocked, "writer never became PostgreSQL-blocked")
            finally:
                release.set()
            verifier.result(timeout=10)
            writer.result(timeout=10)
        self.assertTrue(completed.is_set())

    def test_write_verifier_source_lock_releases_after_rollback(self) -> None:
        entered, attempted, completed, release = Event(), Event(), Event(), Event()
        writer_pid = {}

        def holder() -> None:
            try:
                with self.session_factory.repeatable_read_transaction():
                    verify_persisted_claim_v2_snapshot_write_transaction(
                        session_factory=self.session_factory,
                        report_id=self.report.id, claim_id=self.claim.claim_id,
                        report_repository=PostgreSQLReportRepository(self.session_factory),
                        report_claim_repository=self.claims, finding_repository=self.findings,
                        insight_repository=self.insights, evidence_repository=self.evidence_repo,
                        source_repository=self.sources, workflow_run_repository=self.runs,
                        workflow_template_repository=self.templates,
                    )
                    entered.set()
                    release.wait(timeout=10)
                    raise ValueError("rollback authority transaction")
            finally:
                release.set()

        def writer() -> None:
            factory = DatabaseSessionFactory(self.engine)
            repository = PostgreSQLSourceRepository(factory)
            with factory.transaction() as session:
                current = repository.get_by_id(self.source.id)
                session.execute(text("SET LOCAL lock_timeout='5s'"))
                writer_pid["value"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                attempted.set()
                repository.save(
                    replace(
                        current,
                        metadata={**current.metadata, "discovery_records": ("rollback",)},
                    ),
                    expected_version=current.version,
                )
            completed.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(holder)
            self.assertTrue(entered.wait(timeout=10))
            second = pool.submit(writer)
            try:
                self.assertTrue(attempted.wait(timeout=10))
                deadline = time.monotonic() + 10
                blocked = False
                while time.monotonic() < deadline:
                    with self.engine.connect() as connection:
                        blocked = bool(connection.execute(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": writer_pid["value"]},
                        ).scalar_one())
                    if blocked:
                        break
                    self.assertFalse(completed.is_set())
                    time.sleep(0.05)
                self.assertTrue(blocked, "writer never became PostgreSQL-blocked")
            finally:
                release.set()
            with self.assertRaises(ValueError):
                first.result(timeout=10)
            second.result(timeout=10)
        self.assertTrue(completed.is_set())

    def test_write_verifier_does_not_persist_successor_report_or_claim(self) -> None:
        before_reports = len(PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id))
        before_claims = len(self.claims.list_for_report(self.report.id, self.report.revision_number))
        with self.session_factory.repeatable_read_transaction():
            verify_persisted_claim_v2_snapshot_write_transaction(
                session_factory=self.session_factory,
                report_id=self.report.id,
                claim_id=self.claim.claim_id,
                report_repository=PostgreSQLReportRepository(self.session_factory),
                report_claim_repository=self.claims,
                finding_repository=self.findings,
                insight_repository=self.insights,
                evidence_repository=self.evidence_repo,
                source_repository=self.sources,
                workflow_run_repository=self.runs,
                workflow_template_repository=self.templates,
            )
        self.assertEqual(before_reports, len(PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id)))
        self.assertEqual(before_claims, len(self.claims.list_for_report(self.report.id, self.report.revision_number)))

    def test_changed_finding_is_rejected(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE findings SET statement='changed' WHERE id='finding-v2'"))
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_changed_evidence_is_rejected(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE evidence SET statement='changed' WHERE id='evidence-1'"))
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_changed_source_revision_is_rejected(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE sources SET content_checksum=:checksum WHERE id='source-1'"), {"checksum": "0" * 64})
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_write_verifier_rejects_pinned_source_checksum_mismatch(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE sources SET content_checksum=:checksum WHERE id=:id"), {"checksum": "f" * 64, "id": self.source.id})
        with self.session_factory.repeatable_read_transaction():
            with self.assertRaises(ClaimLineageVerificationV2Error):
                verify_persisted_claim_v2_snapshot_write_transaction(
                    session_factory=self.session_factory,
                    report_id=self.report.id, claim_id=self.claim.claim_id,
                    report_repository=PostgreSQLReportRepository(self.session_factory),
                    report_claim_repository=self.claims, finding_repository=self.findings,
                    insight_repository=self.insights, evidence_repository=self.evidence_repo,
                    source_repository=self.sources, workflow_run_repository=self.runs,
                    workflow_template_repository=self.templates,
                )

    def test_missing_insight_is_rejected(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM insights WHERE id='insight-v2'"))
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_temporal_numeric_authority_change_is_rejected(self) -> None:
        with self.session_factory.session() as session:
            row = session.get(EvidenceModel, self.evidence.id)
            row.metadata_json = {**row.metadata_json, "observation_period": "2020"}
            session.flush()
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_corrupted_jsonb_proposition_is_rejected_during_reload(self) -> None:
        payload = self.claim.to_dict()
        payload["claim_id"] = "corrupt-claim"
        payload["assertion"]["proposition"] = "tampered"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO report_claims "
                    "(id,report_id,report_revision,project_id,source_workflow_run_id,"
                    "report_workflow_run_id,research_design_id,contract_version,"
                    "claim_payload,authority_digest,created_at) VALUES "
                    "(:id,:report_id,:revision,:project_id,:source_run,:report_run,"
                    ":design_id,:contract_version,CAST(:payload AS jsonb),:authority_digest,"
                    "CURRENT_TIMESTAMP)"
                ),
                {
                    "id": "corrupt-claim",
                    "report_id": self.report.id,
                    "revision": self.report.revision_number,
                    "project_id": self.claim.project_id,
                    "source_run": self.claim.source_workflow_run_id,
                    "report_run": self.claim.report_workflow_run_id,
                    "design_id": self.claim.design_id,
                    "contract_version": self.claim.contract_version,
                    "payload": json.dumps(payload),
                    "authority_digest": self.claim.authority_digest,
                },
            )
        with self.assertRaises(ReportClaimContractError):
            PostgreSQLReportClaimRepository(self.session_factory).get_by_id("corrupt-claim")

    def test_structurally_valid_claim_with_stale_authority_is_rejected(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE findings SET rationale='stale' WHERE id='finding-v2'"))
        with self.assertRaises(ClaimLineageVerificationV2Error):
            self.verify_fresh()

    def test_claim_id_only_revision_fails_closed(self) -> None:
        payload = self.claim.to_dict(); payload["claim_id"] = "claim-v2-revision"
        with self.assertRaises(ReportClaimContractError):
            ReportClaim.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
