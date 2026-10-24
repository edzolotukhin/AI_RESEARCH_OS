from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from hashlib import sha256

from application.report.claim_coverage import validate_claim_backed_coverage
from application.ports.report_claim_repository import ReportClaimConflictError
from application.report.claim_generation import ClaimGenerationError, generate_validated_claims
from application.report.claim_rendering import ClaimRenderingError, render_validated_claims, repair_missing_claim_sections
from application.report.coverage_contract import ReportCoverageContract
from domain.reports.report_claim import ReportClaim
from domain.reports.report import Report
from domain.findings.insight import Insight
from application.report.claim_first_report_service import ClaimFirstReportService
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.sources.source import Source
from domain.sources.retrieval_status import RetrievalStatus
from domain.workflow_template_builder import WorkflowTemplateBuilder
from domain.value_objects.executor_type import ExecutorType
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from application.evidence.grounding import verify_grounding
import tests.application.report.test_report_claim_contract as claim_fixtures


class ClaimFirstGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = claim_fixtures.ReportClaimContractTests(); self.fixture.setUp()

    def generate(self, **kwargs):
        return generate_validated_claims(project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id=kwargs.pop("report_workflow_run_id", "source-run"), design=self.fixture.design, findings=(self.fixture.finding,), insights=(), evidence_by_id={"ev-1": self.fixture.evidence}, citation_id_by_source={"source-1": "S1"}, **kwargs)

    def test_actual_generation_path_accepts_supported_authority(self) -> None:
        claim = self.generate()[0]
        self.assertEqual(claim.scope.geography_country, ("ukraine",))
        self.assertEqual(claim.scope.geography_subnational, ("kyiv",))
        self.assertEqual(claim.scope.periods, ("2026", "2026 q1"))
        self.assertEqual(claim.scope.metrics, ("income",))
        self.assertEqual(claim.scope.population_dimensions, ("households",))
        self.assertEqual(claim.scope.numeric_facts[0].unit, "%")

    def test_actual_generation_rejects_each_unsupported_dimension(self) -> None:
        mutations = (
            lambda p: p["scope"]["geography"]["country"].append("poland"),
            lambda p: p["scope"]["periods"].append("2026 q2"),
            lambda p: p["scope"]["metrics"].append("wealth"),
            lambda p: p["scope"]["population_dimensions"].append("employees"),
            lambda p: p["scope"]["numeric_facts"][0].update(value="11"),
            lambda p: p["scope"]["numeric_facts"][0].update(unit="uah"),
            lambda p: p["scope"]["numeric_facts"][0].update(scale="million"),
            lambda p: p["scope"]["numeric_facts"][0]["geography"].append("kyiv"),
            lambda p: p["scope"]["numeric_facts"][0]["periods"].append("2025"),
            lambda p: p["scope"]["numeric_facts"][0]["metrics"].append("wealth"),
            lambda p: p["scope"]["numeric_facts"][0]["population_dimensions"].append("employees"),
        )
        for mutation in mutations:
            def provider(envelope, mutation=mutation):
                result = copy.deepcopy(envelope); mutation(result); return result
            with self.subTest(mutation=mutation), self.assertRaises(ClaimGenerationError): self.generate(candidate_provider=provider)

    def test_missing_scope_foreign_lineage_and_third_run_fail_closed(self) -> None:
        for mutate in (
            lambda p: p.pop("scope"),
            lambda p: p.update(source_workflow_run_id="third-run"),
            lambda p: p["finding_ids"].append("foreign-finding"),
            lambda p: p["evidence_ids"].append("foreign-evidence"),
        ):
            def provider(envelope, mutate=mutate):
                result = copy.deepcopy(envelope); mutate(result); return result
            with self.subTest(mutate=mutate), self.assertRaises(ClaimGenerationError): self.generate(candidate_provider=provider)

    def test_normal_and_replay_ownership(self) -> None:
        normal = self.generate()[0]; replay = self.generate(report_workflow_run_id="replay-run")[0]
        self.assertEqual(normal.source_workflow_run_id, normal.report_workflow_run_id)
        self.assertEqual(replay.source_workflow_run_id, "source-run")
        self.assertEqual(replay.report_workflow_run_id, "replay-run")

    def test_one_bounded_narrowing_correction_succeeds_and_second_failure_closes(self) -> None:
        def invalid(envelope):
            result = copy.deepcopy(envelope); result["scope"]["geography"]["country"].append("poland"); return result
        def corrected(request):
            result = copy.deepcopy(request["candidate"]); result["scope"]["geography"]["country"].remove("poland"); return result
        self.assertEqual(len(self.generate(candidate_provider=invalid, correction_provider=corrected)), 1)
        with self.assertRaises(ClaimGenerationError): self.generate(candidate_provider=invalid, correction_provider=lambda request: request["candidate"])


class ClaimRenderingAndCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        self.design = fixture.design; self.claim = fixture.claim()

    def payload(self, paragraph: dict, *, claim_ids=None):
        return {"sections": [{"section_id": "section-1", "title": "T", "research_question_ids": ["rq-1"], "claim_ids": claim_ids if claim_ids is not None else [self.claim.claim_id], "paragraphs": [paragraph]}]}

    def test_factual_paragraph_and_summary_must_be_claim_bound(self) -> None:
        factual = {"text": "Supported statement", "claim_ids": [self.claim.claim_id], "classification": "factual"}
        result = render_validated_claims(claims=(self.claim,), design=self.design, rendered_payload=self.payload(factual), summary_payload={"summary_units": [factual]})
        section = result.sections[0]
        self.assertEqual(section.claim_refs, (self.claim.claim_id,))
        self.assertEqual(section.finding_refs, self.claim.finding_ids)
        self.assertEqual(section.evidence_refs, self.claim.evidence_ids)
        for invalid in (
            {"text": "fact", "claim_ids": [], "classification": "factual"},
            {"text": "fact", "claim_ids": ["unknown"], "classification": "factual"},
            {"text": "Unsupported 99%", "claim_ids": [self.claim.claim_id], "classification": "factual"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ClaimRenderingError): render_validated_claims(claims=(self.claim,), design=self.design, rendered_payload=self.payload(invalid), summary_payload={"summary_units": [factual]})
        transition = {"text": "Context and implications", "claim_ids": [], "classification": "non_factual"}
        result = render_validated_claims(claims=(self.claim,), design=self.design, rendered_payload={"sections": [{**self.payload(factual)["sections"][0], "paragraphs": [transition, factual]}]}, summary_payload={"summary_units": [factual]})
        self.assertIn("Context", result.sections[0].content)

    def test_summary_numeric_bypass_is_rejected(self) -> None:
        factual = {"text": "Supported", "claim_ids": [self.claim.claim_id], "classification": "factual"}
        with self.assertRaises(ClaimRenderingError): render_validated_claims(claims=(self.claim,), design=self.design, rendered_payload=self.payload(factual), summary_payload={"summary_units": [{"text": "Unsupported 99%", "claim_ids": [self.claim.claim_id], "classification": "factual"}]})

    def test_complete_limited_and_mandatory_repair_are_claim_backed(self) -> None:
        rendered = render_validated_claims(claims=(self.claim,), design=self.design)
        complete = ReportCoverageContract("complete", ("rq-1",), ())
        mandatory = {"rq-1": self.claim.finding_ids}
        self.assertEqual(validate_claim_backed_coverage(claims=(self.claim,), sections=rendered.sections, contract=complete, mandatory_rq_findings=mandatory), ())
        self.assertIn("claim_section_binding_missing:rq-1", validate_claim_backed_coverage(claims=(self.claim,), sections=(), contract=complete, mandatory_rq_findings=mandatory))
        repaired = repair_missing_claim_sections(sections=(), claims=(self.claim,), required_rq_ids=("rq-1",), design=self.design)
        self.assertEqual(validate_claim_backed_coverage(claims=(self.claim,), sections=repaired, contract=complete, mandatory_rq_findings=mandatory), ())
        limited = ReportCoverageContract("limited", ("rq-1",), ("rq-x",))
        self.assertEqual(validate_claim_backed_coverage(claims=(self.claim,), sections=rendered.sections, contract=limited, mandatory_rq_findings=mandatory), ())
        excluded_claim = replace(self.claim, research_question_ids=("rq-1", "rq-x"))
        self.assertIn("excluded_rq_claimed_complete:rq-x", validate_claim_backed_coverage(claims=(excluded_claim,), sections=rendered.sections, contract=limited, mandatory_rq_findings=mandatory))


class ClaimFirstServiceTests(unittest.TestCase):
    def test_new_desk_report_path_persists_report_and_claims_atomically(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        project = ProjectFactory().create("Claim-first")
        evidence = replace(fixture.evidence, project_id=project.id, deduplication_key="evidence-1")
        finding = replace(fixture.finding, project_id=project.id, deduplication_key="finding-1")
        source_text = "E"
        source = Source(id="source-1", project_id=project.id, url="https://example.com/source", canonical_url="https://example.com/source", title="Source", retrieved_at="2026-01-01T00:00:00Z", retrieval_status=RetrievalStatus.ACQUIRED, content_text=source_text, content_checksum=sha256(source_text.encode()).hexdigest(), research_question_refs=("rq-1",), information_need_refs=("in-1",), workflow_run_refs=("source-run",), research_design_refs=(fixture.design.id,))
        evidence.source_content_checksum = source.content_checksum
        evidence.source_locator = verify_grounding(source_text=source_text, excerpt="E").to_dict()
        source_repo = InMemorySourceRepository(); source_repo.create(source)
        evidence_repo = InMemoryEvidenceRepository(); evidence_repo.create(evidence)
        finding_repo = InMemoryFindingRepository(); finding_repo.create(finding)
        insight_repo = InMemoryInsightRepository()
        report_repo = InMemoryReportRepository(); claim_repo = InMemoryReportClaimRepository(report_repo)
        artifact_repo = InMemoryArtifactRepository()
        template = (WorkflowTemplateBuilder(id="template", name="T").add_task(id="report", name="Write", executor_id="report", executor_type=ExecutorType.AGENT).build())
        template.research_brief_snapshot = replace(sample_research_brief(), timeframe=""); template.research_design_snapshot = fixture.design
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="source-run"); run.project_id = project.id
        context = WorkflowContext(project=project, workflow_run=run, workflow_template=template, current_task=run.tasks[0])
        service = ClaimFirstReportService(report_claim_repository=claim_repo, report_engine=DeterministicReportEngine(), finding_repository=finding_repo, insight_repository=insight_repo, evidence_repository=evidence_repo, source_repository=source_repo, report_repository=report_repo, artifact_repository=artifact_repo, max_findings_per_batch=10, max_chars_per_batch=10000)
        summary = service.write_for_context(context)
        report = report_repo.get_by_id(summary.report_id); self.assertIsNotNone(report)
        claims = claim_repo.list_for_report(summary.report_id, 1)
        self.assertEqual(len(claims), 1)
        self.assertEqual(report.sections[0].claim_refs, (claims[0].claim_id,))
        self.assertEqual(report.metadata["structured_claim_contract"], "desk_report_claim_v1")
        self.assertTrue(report.metadata["summary_units"])

    def test_replay_shaped_source_artifacts_remain_immutable_and_report_is_replay_owned(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        source_ids = tuple(f"source-{index}" for index in range(29))
        evidence = tuple(
            replace(
                fixture.evidence,
                id=f"evidence-{index}",
                source_id=source_ids[index % len(source_ids)],
                deduplication_key=f"evidence-{index}",
            )
            for index in range(50)
        )
        findings = tuple(
            replace(
                fixture.finding,
                id=f"finding-{index}",
                evidence_refs=tuple(item.id for item in evidence[index * 10 : (index + 1) * 10]),
                deduplication_key=f"finding-{index}",
            )
            for index in range(5)
        )
        source_snapshot = copy.deepcopy((source_ids, evidence, findings))

        claims = generate_validated_claims(
            project_id="project-1",
            source_workflow_run_id="source-run",
            report_workflow_run_id="replay-run",
            design=fixture.design,
            findings=findings,
            insights=tuple(
                Insight(
                    id=f"insight-{index}",
                    project_id="project-1",
                    workflow_run_id="source-run",
                    research_design_id=fixture.design.id,
                    statement="Supported implication",
                    implication="Supported implication",
                    finding_refs=(findings[index].id,),
                    created_at="2026-01-01T00:00:00Z",
                    research_question_refs=("rq-1",),
                )
                for index in range(5)
            ),
            evidence_by_id={item.id: item for item in evidence},
            citation_id_by_source={source_id: f"S{index + 1}" for index, source_id in enumerate(source_ids)},
        )
        rendered = render_validated_claims(claims=claims, design=fixture.design)
        report = Report(
            id="replay-report",
            project_id="project-1",
            workflow_run_id="replay-run",
            research_design_id=fixture.design.id,
            title="Replay report",
            language="en",
            sections=rendered.sections,
            executive_summary=rendered.executive_summary,
            limitations=(),
            created_at="2026-01-01T00:00:00Z",
            generation_method="claim-first:deterministic",
            finding_refs=tuple(finding.id for finding in findings),
            insight_refs=tuple(f"insight-{index}" for index in range(5)),
            evidence_refs=tuple(item.id for item in evidence),
            citation_registry={},
            deduplication_key="replay-report",
            revision_number=1,
        )
        report_repository = InMemoryReportRepository()
        claim_repository = InMemoryReportClaimRepository(report_repository)
        claim_repository.create_with_report(report, claims)

        self.assertEqual((source_ids, evidence, findings), source_snapshot)
        self.assertEqual(report_repository.get_by_id(report.id).workflow_run_id, "replay-run")
        self.assertEqual(len(claim_repository.list_for_report(report.id, 1)), 5)
        self.assertTrue(all(claim.source_workflow_run_id == "source-run" for claim in claims))
        self.assertTrue(all(claim.report_workflow_run_id == "replay-run" for claim in claims))

        invalid_claim = replace(claims[0], claim_id="invalid-claim", report_workflow_run_id="foreign-run")
        invalid_report = replace(report, id="invalid-report", deduplication_key="invalid-report")
        with self.assertRaises(ReportClaimConflictError):
            claim_repository.create_with_report(invalid_report, (invalid_claim,))
        self.assertIsNone(report_repository.get_by_id(invalid_report.id))


if __name__ == "__main__": unittest.main()
