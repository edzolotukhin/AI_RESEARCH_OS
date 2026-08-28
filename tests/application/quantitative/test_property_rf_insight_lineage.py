from __future__ import annotations

from dataclasses import replace
import unittest

from application.quantitative.insight_lineage import (
    QuantitativeInsightLineageError, QuantitativeInsightLineageService,
)
from application.quantitative.insight_synthesis import (
    QuantitativeInsightSynthesisService, QuantitativeInsightValidator,
)
from domain.quantitative.insight_lineage import InsightCoverageStatus, InsightFindingLineageBranch
from infrastructure.persistence.quantitative_insight_lineage_repository import QLQuantitativeInsightLineageRepository
from tests.application.quantitative.test_property_re_finding_lineage import (
    PropertyREFindingLineageTests as _PropertyREFindingLineageTests,
    RecordingFindingGenerator,
)


class RecordingInsightGenerator:
    identity = "rf-recording-insight-v1"

    def __init__(self, *, design_fields=False, empty=False):
        self.calls = 0
        self.design_fields = design_fields
        self.empty = empty

    def generate(self, prompt):
        self.calls += 1
        if self.empty:
            return {"proposals": []}
        import json
        findings = json.loads(prompt.split("ACCEPTED_FINDINGS=", 1)[1])
        proposal = {
            "insight_type": "SYNTHESIS",
            "insight_text": "The supported pattern warrants synthesis.",
            "supporting_finding_ids": [item["finding_id"] for item in findings],
            "referenced_display_values": [],
            "direction": None,
            "limitation_note": None,
        }
        if self.design_fields:
            proposal["objective_ids"] = ["fabricated-objective"]
        return {"proposals": [proposal]}


class PropertyRFInsightLineageTests(unittest.TestCase):
    def setUp(self):
        self.re_fixture = _PropertyREFindingLineageTests(methodName="runTest")
        self.re_fixture.setUp()
        for name in (
            "rc", "project", "run", "dataset", "codebook", "quality", "projection",
            "storage", "state", "execution_repository", "execution", "manifest",
            "repository", "lineage",
        ):
            setattr(self, name, getattr(self.re_fixture, name))
        self.finding_service = self.re_fixture.finding_service
        self.re_input = self.repository.save_input_authority(self.re_fixture.authority())
        results, comparisons = self.lineage.load_results(self.re_input)
        self.findings = self.finding_service(RecordingFindingGenerator()).generate(
            statistical_results=results,
            comparison_results=comparisons,
            limitations=self.lineage.generation_limitations(self.re_input),
        )
        self.finding_record = f"{self.run}:finding-generation:{self.findings.generation_fingerprint}"
        self.state.persist(self.findings, record_id=self.finding_record, project_id=self.project, run_id=self.run)
        self.re_manifest, self.re_coverage = self.lineage.finalize(
            authority=self.re_input, generation_record_id=self.finding_record,
            generation=self.findings,
        )
        self.rf_repository = QLQuantitativeInsightLineageRepository(self.state)
        self.rf = QuantitativeInsightLineageService(repository=self.rf_repository, digest_provider=self.rc.digest)

    def authority(self, **changes):
        values = dict(
            project_id=self.project, run_id=self.run,
            generation_record_id=self.finding_record, generation=self.findings,
            re_input=self.re_input, re_manifest=self.re_manifest,
            re_coverage=self.re_coverage,
        )
        values.update(changes)
        return self.rf.build_input_authority(**values)

    def insight_service(self, generator):
        return QuantitativeInsightSynthesisService(
            generator=generator,
            validator=QuantitativeInsightValidator(digest_provider=self.rc.digest),
            digest_provider=self.rc.digest,
        )

    def test_current_re_builds_deterministic_safe_branch_preserving_authority(self):
        first, second = self.authority(), self.authority()
        self.assertEqual(first, second)
        self.assertEqual(len(first.finding_entries), len(self.findings.accepted_findings))
        self.assertTrue(first.finding_entries[0].branches)
        self.assertNotIn("respondent-0", repr(first))
        self.assertNotIn("storage", repr(first).lower())

    def test_stale_and_wrong_scope_authority_fails_closed(self):
        cases = (
            {"project_id": "wrong"}, {"run_id": "wrong"},
            {"generation_record_id": "wrong"},
            {"re_manifest": replace(self.re_manifest, input_authority_fingerprint="stale")},
            {"re_coverage": replace(self.re_coverage, fingerprint="stale")},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(QuantitativeInsightLineageError):
                self.authority(**case)

    def test_qj_then_rf_lineage_and_coverage_are_deterministic(self):
        authority = self.rf_repository.save_input_authority(self.authority())
        generator = RecordingInsightGenerator()
        generation = self.insight_service(generator).generate(
            findings=self.findings.accepted_findings,
            post_validator=self.rf.compatibility_validator(authority),
        )
        record = f"{self.run}:insight-generation:{generation.generation_fingerprint}"
        self.state.persist(generation, record_id=record, project_id=self.project, run_id=self.run)
        manifest, coverage = self.rf.finalize(authority=authority, generation_record_id=record, generation=generation)
        replay_manifest, replay_coverage = self.rf.finalize(authority=authority, generation_record_id=record, generation=generation)
        self.assertEqual((manifest, coverage), (replay_manifest, replay_coverage))
        self.assertEqual(generator.calls, 1)
        self.assertEqual(len(manifest.entries), 1)
        entry = manifest.entries[0]
        self.assertTrue(entry.branches_by_finding[0][1])
        self.assertTrue(entry.common_analytical_requirement_ids or entry.common_research_question_ids)
        self.assertIn(InsightCoverageStatus.INSIGHT_SUPPORTED, {item.status for item in coverage.entries})
        self.assertFalse(hasattr(entry, "objective_answered"))

    def test_qj_rf_bundle_fingerprint_is_order_invariant_and_content_bound(self):
        findings = tuple(self.findings.accepted_findings)
        first = replace(
            findings[0],
            finding_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        second = replace(
            findings[0],
            finding_id="00000000-0000-0000-0000-000000000001",
            support_validation_fingerprint="qh-second-fixed-authority",
        )
        service = self.insight_service(RecordingInsightGenerator(empty=True))
        generation_order = service.generate(findings=(first, second))
        lexical_order = service.generate(findings=(second, first))
        self.assertEqual(
            generation_order.input_finding_bundle_fingerprint,
            lexical_order.input_finding_bundle_fingerprint,
        )

        authority = self.authority()
        entry_first = replace(
            authority.finding_entries[0],
            finding_id=first.finding_id,
            qh_validation_fingerprint=first.support_validation_fingerprint,
            safe_finding_projection=self.rf._finding_projection(first),
        )
        entry_second = replace(
            authority.finding_entries[0],
            finding_id=second.finding_id,
            qh_validation_fingerprint=second.support_validation_fingerprint,
            safe_finding_projection=self.rf._finding_projection(second),
        )
        rf_generation_order = self.rf.expected_generation_bundle_fingerprint(
            replace(authority, finding_entries=(entry_first, entry_second)),
        )
        rf_lexical_order = self.rf.expected_generation_bundle_fingerprint(
            replace(authority, finding_entries=(entry_second, entry_first)),
        )
        self.assertEqual(rf_generation_order, rf_lexical_order)
        self.assertEqual(
            generation_order.input_finding_bundle_fingerprint,
            rf_generation_order,
        )

        removed = service.generate(findings=(first,))
        changed_id = service.generate(
            findings=(first, replace(second, finding_id="11111111-1111-1111-1111-111111111111")),
        )
        changed_validation = service.generate(
            findings=(first, replace(second, support_validation_fingerprint="changed-qh-authority")),
        )
        added = service.generate(
            findings=(
                first,
                second,
                replace(first, finding_id="22222222-2222-2222-2222-222222222222"),
            ),
        )
        for semantically_different in (removed, changed_id, changed_validation, added):
            self.assertNotEqual(
                generation_order.input_finding_bundle_fingerprint,
                semantically_different.input_finding_bundle_fingerprint,
            )
        with self.assertRaisesRegex(Exception, "duplicate"):
            service.generate(findings=(first, first))

    def test_same_rq_different_requirements_compatible_but_common_objective_only_rejected(self):
        base = self.authority().finding_entries[0]
        branch = base.branches[0]
        same_rq = replace(branch, analytical_requirement_ids=("requirement-other",))
        second = replace(base, finding_id="finding-second", branches=(same_rq,))
        authority = replace(self.authority(), finding_entries=(base, second))
        fake = replace(
            self.findings.accepted_findings[0], finding_id="finding-second",
            support_validation_fingerprint="qh-second",
        )
        second = replace(second, qh_validation_fingerprint="qh-second")
        authority = replace(authority, finding_entries=(base, second))
        from domain.quantitative.insight import QuantitativeFindingReference, QuantitativeInsight, QuantitativeInsightType
        insight = QuantitativeInsight("i", "Supported synthesis.", QuantitativeInsightType.SYNTHESIS, (
            QuantitativeFindingReference(base.finding_id, base.qh_validation_fingerprint),
            QuantitativeFindingReference(second.finding_id, second.qh_validation_fingerprint),
        ))
        self.assertEqual(self.rf.compatibility_validator(authority)(insight), insight)
        incompatible_branch = replace(same_rq, research_question_ids=("rq-other",), objective_ids=branch.objective_ids)
        incompatible = replace(second, branches=(incompatible_branch,))
        with self.assertRaisesRegex(QuantitativeInsightLineageError, "common requirement or ResearchQuestion"):
            self.rf.compatibility_validator(replace(authority, finding_entries=(base, incompatible)))(insight)

    def test_model_design_fields_and_unknown_finding_are_rejected_without_lineage(self):
        authority = self.authority()
        generated = self.insight_service(RecordingInsightGenerator(design_fields=True)).generate(
            findings=self.findings.accepted_findings,
            post_validator=self.rf.compatibility_validator(authority),
        )
        self.assertEqual(generated.accepted_insights, ())
        self.assertIn("model-authored design authority", generated.rejected_insights[0].reason)

    def test_zero_proposals_persist_empty_lineage_and_truthful_coverage(self):
        authority = self.rf_repository.save_input_authority(self.authority())
        generated = self.insight_service(RecordingInsightGenerator(empty=True)).generate(
            findings=self.findings.accepted_findings,
            post_validator=self.rf.compatibility_validator(authority),
        )
        record = f"{self.run}:insight-generation:{generated.generation_fingerprint}"
        self.state.persist(generated, record_id=record, project_id=self.project, run_id=self.run)
        manifest, coverage = self.rf.finalize(authority=authority, generation_record_id=record, generation=generated)
        self.assertEqual(manifest.entries, ())
        self.assertEqual({item.status for item in coverage.entries}, {InsightCoverageStatus.NO_INSIGHT_PROPOSED})

    def test_dataset_only_absence_is_explicit_restart_safe_and_has_no_design_ids(self):
        generated = self.insight_service(RecordingInsightGenerator()).generate(findings=self.findings.accepted_findings)
        first = self.rf.dataset_only_absence(project_id=self.project, run_id=self.run, generation_record_id="dataset-only-insights", generation=generated)
        second = self.rf.dataset_only_absence(project_id=self.project, run_id=self.run, generation_record_id="dataset-only-insights", generation=generated)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "NO_DESIGN_AWARE_INSIGHT_LINEAGE")
        self.assertNotIn("objective", repr(first).lower())

    def test_production_vertical_restarts_without_second_qj_call(self):
        vertical = self.re_fixture._vertical(RecordingFindingGenerator())
        generator = RecordingInsightGenerator()
        vertical.insights = self.insight_service(generator)
        vertical.insight_lineage = self.rf
        state = vertical._quant_findings(self.project, self.run, self.re_fixture._safe_state())
        first = vertical._quant_insights(self.project, self.run, state)
        second = vertical._quant_insights(self.project, self.run, dict(first))
        self.assertEqual(generator.calls, 1)
        self.assertEqual(first["insight_lineage_manifest_record_id"], second["insight_lineage_manifest_record_id"])
        self.assertEqual(first["insight_coverage_manifest_record_id"], second["insight_coverage_manifest_record_id"])

    def test_reserved_input_without_generation_fails_closed_without_qj_retry(self):
        self.rf_repository.save_input_authority(self.authority())
        vertical = self.re_fixture._vertical(RecordingFindingGenerator())
        generator = RecordingInsightGenerator()
        vertical.insights = self.insight_service(generator)
        vertical.insight_lineage = self.rf
        state = self.re_fixture._safe_state()
        state.update({
            "finding_generation_record_id": self.finding_record,
            "finding_input_authority_record_id": self.re_input.authority_id,
            "finding_lineage_manifest_record_id": self.re_manifest.manifest_id,
            "finding_coverage_manifest_record_id": self.re_coverage.coverage_id,
        })
        with self.assertRaisesRegex(Exception, "retry prohibited"):
            vertical._quant_insights(self.project, self.run, state)
        self.assertEqual(generator.calls, 0)

if __name__ == "__main__":
    unittest.main()
