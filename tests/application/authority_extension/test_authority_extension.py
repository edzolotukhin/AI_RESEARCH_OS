from __future__ import annotations

import unittest
from dataclasses import replace

from application.authority_extension import AuthorityCompositionError, ComposedAuthorityReader, build_composition
from domain.research_authority import ResearchAuthorityExtension
from infrastructure.persistence.memory.in_memory_authority_extension_repository import InMemoryAuthorityExtensionRepository, InMemoryComposedAuthorityRepository
from application.report.claim_authority import ClaimAuthorityError, derive_composed_claim_authority
from application.report.h3_coverage_plan import build_h3_coverage_plan
from application.report.h3_claim_generation import generate_h3_structural_claims, H3CoverageOutcome
from application.research_quality.deterministic_sufficiency_evaluator import DeterministicSufficiencyEvaluator
from application.research_quality.research_readiness_service import ResearchReadinessService
from tests.application.report.test_h3_claim_generation import _Fixture, _valid_response


class _Repo:
    def __init__(self, values): self.values = values
    def list_for_project(self, project_id, *, workflow_run_id=None, **kwargs):
        return [item for item in self.values if item.project_id == project_id and item.workflow_run_id == workflow_run_id]


class AuthorityExtensionTests(unittest.TestCase):
    def extension(self):
        return ResearchAuthorityExtension("ext-1", "project", "design", "parent", "extension", ("in1", "in2"), "gap", "idem", "2026-01-01T00:00:00Z")

    def test_extension_and_composition_are_idempotent_and_digest_is_canonical(self):
        extensions = InMemoryAuthorityExtensionRepository()
        self.assertIs(extensions.create_or_get(self.extension()), extensions.create_or_get(self.extension()))
        first = build_composition(composition_id="composition-1", project_id="project", research_design_id="design", parent_source_workflow_run_id="parent", member_workflow_run_ids=("parent", "extension"), selected_information_need_ids=("in2", "in1"), created_at="now")
        second = build_composition(composition_id="composition-2", project_id="project", research_design_id="design", parent_source_workflow_run_id="parent", member_workflow_run_ids=("extension", "parent"), selected_information_need_ids=("in1", "in2"), created_at="later")
        self.assertEqual(first.composition_digest, second.composition_digest)
        compositions = InMemoryComposedAuthorityRepository()
        self.assertIs(compositions.create_or_get(first), compositions.create_or_get(second))

    def test_reader_preserves_owner_runs_and_rejects_non_members(self):
        class Item:
            def __init__(self, run): self.project_id, self.workflow_run_id = "project", run
        composition = build_composition(composition_id="c", project_id="project", research_design_id="design", parent_source_workflow_run_id="parent", member_workflow_run_ids=("parent", "extension"), selected_information_need_ids=("in1",), created_at="now")
        reader = ComposedAuthorityReader(_Repo([Item("parent"), Item("extension")]), _Repo([Item("extension")]), _Repo([]), _Repo([]))
        self.assertEqual({item.workflow_run_id for item in reader.list_evidence(composition)}, {"extension"})
        with self.assertRaises(AuthorityCompositionError):
            reader.validate_member(composition, project_id="project", research_design_id="design", workflow_run_id="foreign")

    def test_composed_coverage_and_claim_authority_use_extension_findings(self):
        fixture = _Fixture(two=True)
        parent_evidence = tuple(fixture.evidence)
        extension_findings = tuple(
            replace(item, workflow_run_id="extension") for item in fixture.findings
        )
        composition = build_composition(
            composition_id="composition", project_id="project-1",
            research_design_id="design-1", parent_source_workflow_run_id="source-run",
            member_workflow_run_ids=("source-run", "extension"),
            selected_information_need_ids=("in-1", "in-2"), created_at="now",
        )
        parent_plan = build_h3_coverage_plan(
            design=fixture.design, required_information_need_ids=("in-1", "in-2"),
            findings=(), evidence_by_id={item.id: item for item in parent_evidence}, insights=(),
        )
        composed_plan = build_h3_coverage_plan(
            design=fixture.design, required_information_need_ids=("in-1", "in-2"),
            findings=extension_findings,
            evidence_by_id={item.id: item for item in parent_evidence}, insights=(),
        )
        self.assertFalse(parent_plan.is_fully_fillable)
        self.assertTrue(composed_plan.is_fully_fillable)
        result = generate_h3_structural_claims(
            project_id="project-1", source_workflow_run_id="source-run",
            report_workflow_run_id="report-run", design=fixture.design,
            findings=extension_findings, insights=(),
            evidence_by_id={item.id: item for item in parent_evidence},
            citation_id_by_source={"source-1": "S1", "source-2": "S2"},
            candidate_provider=_valid_response, correction_provider=None,
            required_research_question_ids=("rq-1", "rq-2"),
            required_information_need_ids=("in-1", "in-2"),
            coverage_plan=composed_plan, composed_authority=composition,
        )
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.SUCCESS)
        provenance = result.claims[0].structural_assertion["composed_authority"]
        self.assertEqual(provenance["composition_digest"], composition.composition_digest)

    def test_composed_claim_authority_rejects_non_member_and_foreign_design(self):
        fixture = _Fixture()
        composition = build_composition(
            composition_id="composition", project_id="project-1",
            research_design_id="design-1", parent_source_workflow_run_id="source-run",
            member_workflow_run_ids=("source-run", "extension"),
            selected_information_need_ids=("in-1",), created_at="now",
        )
        evidence = {item.id: item for item in fixture.evidence}
        with self.assertRaises(ClaimAuthorityError):
            derive_composed_claim_authority(
                composition=composition, report_workflow_run_id="report-run",
                design=fixture.design,
                findings=(replace(fixture.findings[0], workflow_run_id="foreign"),),
                evidence_by_id=evidence,
            )

    def test_source_independence_is_not_inflated_across_members(self):
        fixture = _Fixture(two=True)
        first = replace(fixture.evidence[0], metadata={"data_lineage": {"status": "established", "origin_id": "A retail dataset"}})
        duplicate = replace(fixture.evidence[1], source_id="source-other-row", information_need_refs=("in-1",), research_question_refs=("rq-1",), metadata={"data_lineage": {"status": "established", "origin_id": "A retail dataset"}})
        signals = DeterministicSufficiencyEvaluator().evaluate(design=fixture.design, evidence=(first, duplicate))
        self.assertEqual(signals[0].independent_source_count, 1)
        independent = replace(duplicate, metadata={"data_lineage": {"status": "established", "origin_id": "B retail dataset"}})
        signals = DeterministicSufficiencyEvaluator().evaluate(design=fixture.design, evidence=(first, independent))
        self.assertEqual(signals[0].independent_source_count, 2)

    def test_readiness_selects_union_only_for_explicit_composition(self):
        fixture = _Fixture(two=True)
        parent = replace(fixture.evidence[0], workflow_run_id="parent")
        extension = replace(fixture.evidence[1], workflow_run_id="extension")
        composition = build_composition(
            composition_id="composition", project_id="project-1",
            research_design_id="design-1", parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "extension"),
            selected_information_need_ids=("in-1", "in-2"), created_at="now",
        )
        compositions = InMemoryComposedAuthorityRepository()
        compositions.create_or_get(composition)

        class Context:
            project = type("Project", (), {"id": "project-1"})()
            workflow_run = type("Run", (), {"id": "parent"})()
            workflow_template = type("Template", (), {"research_design_snapshot": fixture.design})()
            def read_shared(self, key):
                return ({"composition_id": composition.composition_id,
                         "composition_digest": composition.composition_digest}
                        if key == "research_authority_composition_v1" else None)

        service = ResearchReadinessService(
            evaluator=DeterministicSufficiencyEvaluator(),
            evidence_repository=_Repo((parent, extension)),
            composed_authority_repository=compositions,
        )
        selected = service._evidence_for_context(Context())
        self.assertEqual({item.workflow_run_id for item in selected}, {"parent", "extension"})


if __name__ == "__main__":
    unittest.main()
