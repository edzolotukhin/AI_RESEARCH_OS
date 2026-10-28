from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from hashlib import sha256

from application.evidence.grounding import verify_grounding
from application.ports.report_claim_repository import ReportClaimConflictError
from application.report.claim_first_report_service import ClaimFirstReportService
from application.report.editorial_composer import EditorialComposer
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION
from application.report.exceptions import ReportError
from application.report.presentation_persistence import (
    EDITORIAL_ENVELOPE_KEY,
    REPORT_CONTRACT_KEY,
    PresentationPersistenceError,
    attach_editorial_envelope,
    presentation_report_digest,
    presentation_report_from_dict,
    presentation_report_to_dict,
    read_presentation_report,
    report_claims_authority_digest,
)
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.reports.report import Report
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.postgresql.mappers.report_mapper import report_from_model, report_to_model
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
import tests.application.report.test_report_claim_contract as claim_fixtures
import tests.application.report.test_editorial_composer as editorial_fixtures


class _RuntimeEditorialProvider:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.requests: list[dict] = []

    def generate(self, request):
        self.requests.append(copy.deepcopy(request))
        if self.invalid:
            return {"invalid": True}
        claim = request["claims"][0]
        fact_ref = claim["fact_refs"][0]
        claim_ref = claim["claim_ref"]
        paragraph = {
            "paragraph_id": "paragraph-1",
            "group_refs": [],
            "segments": [
                {"type": "TEXT", "text": "Підтверджений показник становить "},
                {"type": "FACT_REF", "claim_ref": claim_ref, "fact_ref": fact_ref, "variant": "value_with_unit"},
                {"type": "TEXT", "text": "."},
            ],
        }
        return {
            "contract_version": EDITORIAL_CONTRACT_VERSION,
            "report_title": "Провайдерський заголовок",
            "executive_summary": [paragraph],
            "sections": [{
                "section_id": "section-1",
                "title": "Підтверджені результати",
                "purpose": "Виклад підтверджених результатів",
                "paragraphs": [{**paragraph, "paragraph_id": "paragraph-2"}],
            }],
        }


class _FailingAtomicClaimRepository(InMemoryReportClaimRepository):
    def create_with_report(self, report, claims):
        raise ReportClaimConflictError("forced persistence failure")


class PresentationEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = editorial_fixtures.EditorialComposerTests()
        fixture.setUp()
        self.claims = fixture.claims
        self.result, _ = fixture.compose(fixture.valid)
        self.presentation = self.result.report
        self.authority_digest = report_claims_authority_digest(self.claims)
        self.presentation = replace(
            self.presentation, authority_digest=self.authority_digest,
            source_report_id=self.presentation.report_id,
        )
        self.diagnostics = {
            **self.result.diagnostics,
            "authority_digest": self.authority_digest,
            "presentation_digest": presentation_report_digest(self.presentation),
        }
        self.report = Report(
            id=self.presentation.report_id, project_id="project-1", workflow_run_id="run-1",
            research_design_id="design-1", title=self.presentation.title, language="uk",
            sections=(), executive_summary="", limitations=(), created_at="2026-01-01T00:00:00+00:00",
            generation_method="claim-first:test", finding_refs=(), insight_refs=(), evidence_refs=(),
            citation_registry={}, deduplication_key="report-1", revision_number=self.presentation.revision_number,
            metadata=attach_editorial_envelope({}, presentation=self.presentation, claims=self.claims, diagnostics=self.diagnostics),
        )

    def test_legacy_metadata_is_readable_and_not_misclassified(self) -> None:
        legacy = replace(self.report, metadata={"structured_claim_contract": "desk_report_claim_v1"})
        self.assertIsNone(read_presentation_report(legacy, claims=self.claims))

    def test_envelope_round_trips_deterministically(self) -> None:
        payload = presentation_report_to_dict(self.presentation)
        rebuilt = presentation_report_from_dict(copy.deepcopy(payload))
        self.assertEqual(payload, presentation_report_to_dict(rebuilt))
        self.assertEqual(self.presentation, read_presentation_report(self.report, claims=self.claims))
        self.assertEqual(presentation_report_digest(self.presentation), presentation_report_digest(rebuilt))

    def test_report_metadata_json_mapper_round_trips_envelope(self) -> None:
        model = report_to_model(self.report, version=1)
        rebuilt = report_from_model(model)
        self.assertEqual(self.report.metadata, rebuilt.metadata)
        self.assertEqual(self.presentation, read_presentation_report(rebuilt, claims=self.claims))

    def test_new_contract_identity_and_schema_fail_closed(self) -> None:
        mutations = (
            lambda item: item.metadata.update({REPORT_CONTRACT_KEY: "wrong"}),
            lambda item: item.metadata.pop(EDITORIAL_ENVELOPE_KEY),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY]["presentation_report"].update({"report_id": "wrong"}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY]["presentation_report"].update({"revision_number": 99}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY].update({"authority_digest": "wrong"}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY].update({"presentation_digest": "wrong"}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY]["presentation_report"].update({"unknown": True}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY].update({"unknown": True}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY]["presentation_report"].update({"sections": "invalid"}),
            lambda item: item.metadata[EDITORIAL_ENVELOPE_KEY]["presentation_report"].update({"title": "Інший заголовок"}),
        )
        for mutate in mutations:
            candidate = copy.deepcopy(self.report)
            mutate(candidate)
            with self.subTest(mutate=mutate), self.assertRaises(PresentationPersistenceError):
                read_presentation_report(candidate, claims=self.claims)

    def test_authority_digest_is_order_stable_and_fact_sensitive(self) -> None:
        self.assertEqual(
            report_claims_authority_digest(self.claims),
            report_claims_authority_digest(tuple(reversed(self.claims))),
        )
        reordered_scope = replace(
            self.claims[0].scope,
            geography_country=tuple(reversed(self.claims[0].scope.geography_country)),
            periods=tuple(reversed(self.claims[0].scope.periods)),
            metrics=tuple(reversed(self.claims[0].scope.metrics)),
            numeric_facts=tuple(reversed(self.claims[0].scope.numeric_facts)),
        )
        reordered = replace(self.claims[0], scope=reordered_scope)
        self.assertEqual(
            report_claims_authority_digest(self.claims),
            report_claims_authority_digest((reordered, *self.claims[1:])),
        )
        fact = self.claims[0].scope.numeric_facts[0]
        changed = replace(
            self.claims[0],
            scope=replace(self.claims[0].scope, numeric_facts=(replace(fact, value="999"),)),
        )
        self.assertNotEqual(
            report_claims_authority_digest(self.claims),
            report_claims_authority_digest((changed, *self.claims[1:])),
        )
        wording = replace(self.claims[0], proposition="Інше формулювання")
        self.assertEqual(
            report_claims_authority_digest(self.claims),
            report_claims_authority_digest((wording, *self.claims[1:])),
        )

    def test_presentation_digest_covers_reader_facing_identity_not_diagnostics(self) -> None:
        baseline = presentation_report_digest(self.presentation)
        first = self.presentation.executive_summary.paragraphs[0]
        changed_paragraph = replace(first, text=first.text + " Уточнення.")
        changed_summary = replace(
            self.presentation.executive_summary,
            paragraphs=(changed_paragraph, *self.presentation.executive_summary.paragraphs[1:]),
        )
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, executive_summary=changed_summary)))
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, title="Інший заголовок")))
        citation = self.presentation.citations[0]
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, citations=(replace(citation, display_key="X"), *self.presentation.citations[1:]))))
        limitation = self.presentation.limitations[0]
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, limitations=(replace(limitation, topic_ref="other"),))))
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, sections=tuple(reversed(self.presentation.sections)))))
        self.assertNotEqual(baseline, presentation_report_digest(replace(self.presentation, executive_summary=replace(self.presentation.executive_summary, paragraphs=tuple(reversed(self.presentation.executive_summary.paragraphs))))))
        self.assertEqual(self.authority_digest, report_claims_authority_digest(self.claims))
        metadata_a = attach_editorial_envelope({}, presentation=self.presentation, claims=self.claims, diagnostics=self.diagnostics)
        metadata_b = attach_editorial_envelope({}, presentation=self.presentation, claims=self.claims, diagnostics={**self.diagnostics, "stage": "different"})
        self.assertEqual(metadata_a[EDITORIAL_ENVELOPE_KEY]["presentation_digest"], metadata_b[EDITORIAL_ENVELOPE_KEY]["presentation_digest"])


class PresentationRuntimeIntegrationTests(unittest.TestCase):
    def _fixture(self, *, provider=None, claim_repository_factory=InMemoryReportClaimRepository, contract=EDITORIAL_CONTRACT_VERSION):
        source_fixture = claim_fixtures.ReportClaimContractTests(); source_fixture.setUp()
        project = ProjectFactory().create("Claim-first")
        evidence = replace(source_fixture.evidence, project_id=project.id, deduplication_key="evidence-1")
        finding = replace(source_fixture.finding, project_id=project.id, deduplication_key="finding-1")
        source = Source(id="source-1", project_id=project.id, url="https://example.com/source", canonical_url="https://example.com/source", title="Source", retrieved_at="2026-01-01T00:00:00Z", retrieval_status=RetrievalStatus.ACQUIRED, content_text="E", content_checksum=sha256(b"E").hexdigest(), research_question_refs=("rq-1",), information_need_refs=("in-1",), workflow_run_refs=("source-run",), research_design_refs=(source_fixture.design.id,))
        evidence.source_content_checksum = source.content_checksum
        evidence.source_locator = verify_grounding(source_text="E", excerpt="E").to_dict()
        source_repo = InMemorySourceRepository(); source_repo.create(source)
        evidence_repo = InMemoryEvidenceRepository(); evidence_repo.create(evidence)
        finding_repo = InMemoryFindingRepository(); finding_repo.create(finding)
        report_repo = InMemoryReportRepository()
        claim_repo = claim_repository_factory(report_repo)
        artifact_repo = InMemoryArtifactRepository()
        template = WorkflowTemplateBuilder(id="template", name="T").add_task(id="report", name="Write", executor_id="report", executor_type=ExecutorType.AGENT).build()
        template.research_brief_snapshot = replace(sample_research_brief(), timeframe="")
        template.research_design_snapshot = source_fixture.design
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="source-run"); run.project_id = project.id
        context = WorkflowContext(project=project, workflow_run=run, workflow_template=template, current_task=run.tasks[0])
        kwargs = {}
        if contract == EDITORIAL_CONTRACT_VERSION:
            kwargs = {"report_contract_version": contract, "editorial_composer": EditorialComposer(provider)}
        service = ClaimFirstReportService(report_claim_repository=claim_repo, report_engine=DeterministicReportEngine(), finding_repository=finding_repo, insight_repository=InMemoryInsightRepository(), evidence_repository=evidence_repo, source_repository=source_repo, report_repository=report_repo, artifact_repository=artifact_repo, max_findings_per_batch=10, max_chars_per_batch=10000, **kwargs)
        return service, context, report_repo, claim_repo, artifact_repo, template.research_brief_snapshot.title

    def test_explicit_editorial_mode_persists_exact_revision_without_legacy_artifact(self) -> None:
        provider = _RuntimeEditorialProvider()
        service, context, reports, claims, artifacts, system_title = self._fixture(provider=provider)
        summary = service.write_for_context(context)
        report = reports.get_by_id(summary.report_id)
        stored_claims = tuple(claims.list_for_report(report.id, report.revision_number))
        presentation = read_presentation_report(report, claims=stored_claims)
        self.assertEqual(report.id, presentation.report_id)
        self.assertEqual(report.revision_number, presentation.revision_number)
        self.assertEqual(report.id, presentation.source_report_id)
        self.assertEqual(system_title, presentation.title)
        self.assertNotEqual("Провайдерський заголовок", presentation.title)
        self.assertEqual("", summary.artifact_id)
        self.assertEqual([], artifacts.list_for_run(context.workflow_run.id))
        self.assertEqual(1, len(provider.requests))
        diagnostics = report.metadata[EDITORIAL_ENVELOPE_KEY]["diagnostics"]
        self.assertEqual(1, diagnostics["provider_call_count"])
        self.assertEqual(report_claims_authority_digest(stored_claims), report.metadata[EDITORIAL_ENVELOPE_KEY]["authority_digest"])

    def test_composer_failure_persists_nothing_and_never_falls_back(self) -> None:
        provider = _RuntimeEditorialProvider(invalid=True)
        service, context, reports, claims, artifacts, _ = self._fixture(provider=provider)
        with self.assertRaises(ReportError):
            service.write_for_context(context)
        self.assertEqual([], reports.list_for_project(context.project.id))
        self.assertEqual([], artifacts.list_for_run(context.workflow_run.id))
        self.assertEqual([], claims.list_for_report("missing", 1))
        self.assertEqual(2, len(provider.requests))
        self.assertEqual("failed", context.read_shared("report_generation_diagnostics")["status"])

    def test_atomic_persistence_failure_leaves_no_report_claim_or_artifact(self) -> None:
        provider = _RuntimeEditorialProvider()
        service, context, reports, claims, artifacts, _ = self._fixture(provider=provider, claim_repository_factory=_FailingAtomicClaimRepository)
        with self.assertRaises(ReportError):
            service.write_for_context(context)
        self.assertEqual([], reports.list_for_project(context.project.id))
        self.assertEqual([], claims.list_for_report("missing", 1))
        self.assertEqual([], artifacts.list_for_run(context.workflow_run.id))
        self.assertEqual("atomic_persistence", context.read_shared("report_generation_diagnostics")["phase"])

    def test_legacy_default_remains_unchanged_and_creates_markdown_artifact(self) -> None:
        service, context, reports, _, artifacts, _ = self._fixture(provider=None, contract="desk_report_claim_v1")
        summary = service.write_for_context(context)
        report = reports.get_by_id(summary.report_id)
        self.assertNotIn(REPORT_CONTRACT_KEY, report.metadata)
        self.assertIsNotNone(artifacts.get_by_id(summary.artifact_id))


if __name__ == "__main__":
    unittest.main()
