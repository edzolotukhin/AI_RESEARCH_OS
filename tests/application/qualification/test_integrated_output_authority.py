"""Strict integration boundaries for derived H3 authority and OUTPUT materials."""
from dataclasses import replace
from unittest import TestCase

from application.deliverables.output_requirements import verified_output_materials
from application.report.h3_claim_generation import generate_h3_structural_claims, H3CoverageOutcome
from application.report.h3_editorial_delivery import build_h3_editorial_catalog
from domain.reports.report import Report
from tests.application.analysis.test_executable_derivations import setup_memory, derived_design
from tests.application.research_quality.test_classified_readiness import readiness
from tests.application.report.test_h3_claim_generation import _valid_response


class IntegratedOutputAuthorityTests(TestCase):
    def test_revision_loads_exact_persisted_review_and_refuses_foreign_linkage(self):
        from types import SimpleNamespace
        from application.executors.revision_executor import RevisionExecutor, RevisionUnavailableError
        from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
        from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
        from tests.application.executors.test_h3_revision_executor import _review
        from tests.helpers.workflow_run_builder import make_workflow_run
        from runtime.workflow_context import WorkflowContext
        from domain.project import Project
        from domain.workflow_template import WorkflowTemplate
        for foreign in (False, True):
            context = WorkflowContext(project=Project("project-1", "Fixture"),
                workflow_run=make_workflow_run(run_id="report-run"),
                workflow_template=WorkflowTemplate("template", "Fixture", (), research_design_snapshot=SimpleNamespace(id="design-1")))
            context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
            context.write_shared("review_1", {"review_id": "review-1", "report_id": "report", "verdict": "revise"})
            review = _review("report")
            if foreign:
                review = replace(review, workflow_run_id="foreign-run")
            repository = InMemoryReviewRepository(); repository.create(review)
            calls = []
            def revise(context, *, review_result):
                calls.append(review_result.id)
                return {"revision_count": 1}
            executor = RevisionExecutor(SimpleNamespace(revise_for_context=revise), review_repository=repository)
            if foreign:
                with self.assertRaises(RevisionUnavailableError):
                    executor.run(context)
                self.assertEqual(calls, [])
            else:
                executor.run(context)
                self.assertEqual(calls, ["review-1"])

    def authority(self):
        model = derived_design()
        model = replace(model, information_needs=tuple(replace(n, output_format="table") if n.id == "table" else n for n in model.information_needs))
        context, analysis, findings, evidence, sources, _ = setup_memory(model)
        readiness(context, evidence, sources)
        analysis.analyze_for_context(context)
        return context, findings.list_for_project("project"), {e.id: e for e in evidence.list_for_project("project")}, sources

    def generate(self, context, findings, evidence, sources):
        return generate_h3_structural_claims(project_id="project", source_workflow_run_id="run", report_workflow_run_id="run",
            design=context.workflow_template.research_design_snapshot, findings=tuple(findings), evidence_by_id=evidence, insights=(),
            citation_id_by_source={"source": "S1"}, candidate_provider=_valid_response, correction_provider=None,
            required_research_question_ids=("rq-pop",), required_information_need_ids=tuple(n.id for n in context.workflow_template.research_design_snapshot.information_needs if n.id != "table"),
            source_repository=sources, brief=context.workflow_template.research_brief_snapshot)

    def report(self, result):
        return Report(id="report", project_id="project", workflow_run_id="run", research_design_id="design", title="Synthetic",
            language="uk", sections=(), executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
            generation_method="fixture", finding_refs=tuple(ref for c in result.claims for ref in c.finding_ids), insight_refs=(),
            evidence_refs=tuple(ref for c in result.claims for ref in c.evidence_ids), citation_registry={}, deduplication_key="report", revision_number=1,
            metadata={"structured_claim_contract": "desk_h3_structural_claim_v1"})

    def test_shared_source_catalog_and_verified_output_series(self):
        context, findings, evidence, sources = self.authority()
        result = self.generate(context, findings, evidence, sources)
        self.assertNotEqual(result.coverage_outcome, H3CoverageOutcome.TECHNICAL_ERROR)
        report = self.report(result)
        catalog = build_h3_editorial_catalog(report=report, claims=result.claims, coverage_contract_digest="coverage")
        self.assertEqual(len(catalog.authority.citations), 7)
        self.assertEqual({c.display_key for c in catalog.authority.citations.values()}, {"S1"})
        tables, charts, proof = verified_output_materials(design=context.workflow_template.research_design_snapshot, claims=result.claims, report=report)
        self.assertEqual([row[:2] for row in tables[0].rows], [("2019", "1000"), ("2020", "950"), ("2021", "900")])
        self.assertTrue(all(r["satisfied"] for r in proof["requirements"]))

    def test_forged_derivation_or_invalid_citation_cannot_enter_h3_authority(self):
        context, findings, evidence, sources = self.authority()
        for damage in ("result", "citation"):
            altered = []
            for f in findings:
                if damage == "result" and f.metadata.get("derivation"):
                    f = replace(f, metadata={**f.metadata, "derivation": {**f.metadata["derivation"], "rounded_result": "999"}})
                altered.append(f)
            values = {key: replace(e, source_content_checksum="invalid") for key, e in evidence.items()} if damage == "citation" else evidence
            result = self.generate(context, altered, values, sources)
            self.assertEqual(result.coverage_outcome, H3CoverageOutcome.TECHNICAL_ERROR)
            self.assertEqual(result.provider_attempt_count, 0)

    def test_output_refuses_missing_format_missing_period_and_foreign_claim(self):
        context, findings, evidence, sources = self.authority()
        result = self.generate(context, findings, evidence, sources)
        report = self.report(result)
        model = context.workflow_template.research_design_snapshot
        unknown = replace(model, information_needs=tuple(replace(n, output_format="") if n.id == "table" else n for n in model.information_needs))
        with self.assertRaisesRegex(ValueError, "explicit_format"):
            verified_output_materials(design=unknown, claims=result.claims, report=report)
        with self.assertRaisesRegex(ValueError, "scope_mismatch"):
            verified_output_materials(design=model, claims=tuple(replace(c, project_id="foreign") for c in result.claims), report=report)
        incomplete = tuple(replace(c, scope=replace(c.scope, numeric_facts=tuple(f for f in c.scope.numeric_facts if "2020" not in f.periods))) for c in result.claims)
        with self.assertRaisesRegex(ValueError, "period_missing"):
            verified_output_materials(design=model, claims=incomplete, report=report)
