from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from application.report.claim_generation import ClaimGenerationError, generate_validated_claims
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
import tests.application.report.test_report_claim_contract as claim_fixtures
from tests.application.report.hybrid_claim_helpers import LegacyClaimProviderAdapter


class ClaimRepairContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = claim_fixtures.ReportClaimContractTests()
        self.fixture.setUp()

    def generate(self, repair):
        def invalid(envelope):
            result = copy.deepcopy(envelope)
            result["scope"]["geography"]["country"].append("poland")
            return result

        adapter = LegacyClaimProviderAdapter()
        return generate_validated_claims(
            project_id="project-1", source_workflow_run_id="source-run",
            report_workflow_run_id="replay-run", design=self.fixture.design,
            findings=(self.fixture.finding,), insights=(),
            evidence_by_id={"ev-1": self.fixture.evidence},
            citation_id_by_source={"source-1": "S1"},
            candidate_provider=adapter.initial(invalid), correction_provider=adapter.repair(repair),
        )

    @staticmethod
    def semantic_delta(request):
        candidate = request["candidate"]
        return {"claim_id": candidate["claim_id"], "assertion": copy.deepcopy(candidate["assertion"])}

    def test_simultaneous_structural_omissions_reconstruct_complete_claim(self) -> None:
        claims = self.generate(self.semantic_delta)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].research_question_ids, ("rq-1",))
        self.assertEqual(claims[0].support_evidence_ids, ("ev-1",))
        self.assertEqual(claims[0].scope.geography_country, ("ukraine",))

    def test_null_support_scope_validation_and_provenance_reconstruct(self) -> None:
        def repair(request):
            result = self.semantic_delta(request)
            result.update(support=None, scope=None, validation=None, research_question_ids=None,
                          information_need_ids=None, finding_ids=None, evidence_ids=None)
            return result
        self.assertEqual(len(self.generate(repair)), 1)

    def test_malformed_support_shapes_fail_qualified(self) -> None:
        for value in ([], "support", 7, True):
            def repair(request, value=value):
                result = self.semantic_delta(request)
                result["support"] = value
                return result
            with self.subTest(value=value), self.assertRaises(ClaimGenerationError) as captured:
                self.generate(repair)
            diagnostic = captured.exception.diagnostics
            self.assertEqual(diagnostic["container"], "support")
            self.assertEqual(diagnostic["failure_reason"], "container_malformed")

    def test_support_and_top_level_evidence_mismatch_fails_qualified(self) -> None:
        def repair(request):
            result = self.semantic_delta(request)
            result["support"] = {"evidence_ids": []}
            return result
        with self.assertRaises(ClaimGenerationError) as captured:
            self.generate(repair)
        self.assertEqual(captured.exception.diagnostics["field"], "support.evidence_ids")
        self.assertEqual(captured.exception.diagnostics["failure_reason"], "field_empty")

    def test_digest_maps_are_system_derived(self) -> None:
        def repair(request):
            result = self.semantic_delta(request)
            result["support"] = {"finding_content_digests": None, "evidence_content_digests": None}
            return result
        claim = self.generate(repair)[0]
        self.assertEqual(set(claim.finding_content_digests), set(claim.finding_ids))
        self.assertEqual(set(claim.evidence_content_digests), set(claim.evidence_ids))

    def test_digest_injection_fails_closed(self) -> None:
        def repair(request):
            result = self.semantic_delta(request)
            result["support"] = {"finding_content_digests": {"foreign": "digest"}}
            return result
        with self.assertRaises(ClaimGenerationError) as captured:
            self.generate(repair)
        self.assertEqual(captured.exception.diagnostics["failure_reason"], "digest_selection_mismatch")

    def test_assertion_malformed_or_missing_fails_qualified(self) -> None:
        for value in (None, {}, {"proposition": "text"}):
            def repair(request, value=value):
                result = {"claim_id": request["candidate"]["claim_id"]}
                if value is not None:
                    result["assertion"] = value
                return result
            with self.subTest(value=value), self.assertRaises(ClaimGenerationError) as captured:
                self.generate(repair)
            self.assertEqual(captured.exception.diagnostics["container"], "assertion")

    def test_validation_and_version_are_system_derived_and_conflicts_fail(self) -> None:
        self.assertEqual(len(self.generate(self.semantic_delta)), 1)
        for field, value in (("version", "foreign"), ("validation", {"status": "draft"})):
            def repair(request, field=field, value=value):
                result = self.semantic_delta(request)
                result[field] = value
                return result
            with self.subTest(field=field), self.assertRaises(ClaimGenerationError) as captured:
                self.generate(repair)
            self.assertEqual(captured.exception.diagnostics["failure_reason"], "system_value_conflict")

    def test_production_shaped_support_omission_null_and_malformed_shapes(self) -> None:
        evidence_ids = (
            "23a7bf80-7a4c-46be-825e-8d195b794c9d",
            "581f17b0-afb9-4f42-bc6c-fd278a6d042a",
            "896afd02-75af-4531-b048-adf421059b57",
            "8ce678a6-c595-4576-93f4-0595f8ed9f9f",
            "ea5247af-efba-49a8-9458-343dd1289222",
        )
        rq_id = "rq3_ecommerce_shift"
        in_ids = ("in6_ecom_size_penetration", "in7_online_offline_mix")
        design = ResearchDesign(
            id="design-production-shape",
            research_questions=(ResearchQuestion(id=rq_id, question="Q"),),
            information_needs=tuple(
                InformationNeed(id=value, research_question_id=rq_id, description="N")
                for value in in_ids
            ),
        )
        evidence = tuple(
            replace(
                self.fixture.evidence, id=value, source_id=f"source-{index}",
                research_design_id=design.id, research_question_refs=(rq_id,),
                information_need_refs=in_ids,
            )
            for index, value in enumerate(evidence_ids)
        )
        finding = replace(
            self.fixture.finding, id="2d13be7b-3aa2-4e8d-ab35-7ea64ffc77c6",
            research_design_id=design.id, evidence_refs=evidence_ids,
            research_question_refs=(rq_id,), information_need_refs=in_ids,
        )

        def run(repair):
            def invalid(envelope):
                result = copy.deepcopy(envelope)
                result["scope"]["geography"]["country"].append("poland")
                return result
            adapter = LegacyClaimProviderAdapter()
            return generate_validated_claims(
                project_id="project-1", source_workflow_run_id="source-run",
                report_workflow_run_id="replay-run", design=design,
                findings=(finding,), insights=(), evidence_by_id={item.id: item for item in evidence},
                citation_id_by_source={item.source_id: f"S{index}" for index, item in enumerate(evidence)},
                candidate_provider=adapter.initial(invalid), correction_provider=adapter.repair(repair),
            )

        for support in ("omitted", None):
            def repair(request, support=support):
                result = {"claim_id": request["candidate"]["claim_id"],
                          "assertion": copy.deepcopy(request["candidate"]["assertion"])}
                if support != "omitted":
                    result["support"] = support
                return result
            with self.subTest(support=support):
                claim = run(repair)[0]
                self.assertEqual(claim.finding_ids, (finding.id,))
                self.assertEqual(claim.evidence_ids, evidence_ids)
        for support in ([], "support", 7, True):
            def malformed(request, support=support):
                return {"claim_id": request["candidate"]["claim_id"],
                        "assertion": copy.deepcopy(request["candidate"]["assertion"]),
                        "support": support}
            with self.subTest(support=support), self.assertRaises(ClaimGenerationError) as captured:
                run(malformed)
            self.assertEqual(captured.exception.diagnostics["container"], "support")


if __name__ == "__main__":
    unittest.main()
