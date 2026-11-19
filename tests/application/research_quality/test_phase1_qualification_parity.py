from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from application.methods.desk.adapter import DeskAdapter, ASSESSMENT
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from tests.application.analysis.test_executable_derivations import setup_memory


def assessment(result):
    return next(n for rq in result.research_question_assessments
                for n in rq.information_need_assessments if n.information_need_id == "in-pop")


class QualificationParityTests(unittest.TestCase):
    def setUp(self):
        self.context, _, _, self.evidence, self.sources, _ = setup_memory()
        self.service = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=self.evidence, source_repository=self.sources,
        )
        self.adapter = DeskAdapter(
            self.context, NS(source_acquisition_max_seconds=60),
            NS(initial_queries=lambda: (), extraction=NS(_source_repository=self.sources)),
            self.service, self.evidence,
        )

    def check_parity(self, count):
        result = self.service.evaluate_for_context(self.context)
        observation = self.adapter.observe(NS())
        cold = self.adapter.last_result
        self.context.shared_state[ASSESSMENT] = {
            "fingerprint": observation.fingerprint, "result": result.to_dict(),
        }
        self.adapter.observe(NS())
        warm = self.adapter.last_result
        terminal = self.service._finalize_terminal_readiness(self.context, warm)
        counts = tuple(assessment(r).evidence_count for r in (result, cold, warm, terminal))
        self.assertEqual(counts, (count,) * 4)
        self.assertEqual(len(self.adapter.qualified()), count)
        if observation.gaps:
            gap = next(g for g in observation.gaps if g.need_id == "in-pop")
            self.assertEqual(gap.qualifying_count, count)
        print("PARITY service/cold/warm/terminal", counts,
              "accepted IDs", sorted(e.id for e in self.adapter.qualified()))
        return cold

    def test_three_valid_observations_cold_warm_and_terminal(self):
        self.check_parity(3)

    def test_forged_cell_is_rejected_by_all_consumers(self):
        for item in self.evidence.list_for_project("project"):
            item.metadata["normalized_numeric_value"] = "999999"
        self.check_parity(0)

    def test_forged_authoritative_source_cells_are_rejected(self):
        source = self.sources.get_by_id("source")
        for row in source.metadata["structured_tables_v2"]:
            for cell in row["cells"]:
                if cell["header"] == "Population":
                    cell["numeric_value"] = "999999"
        with patch.object(self.sources, "get_by_id", return_value=source):
            self.check_parity(0)

    def test_wrong_revision_is_rejected_by_all_consumers(self):
        for item in self.evidence.list_for_project("project"):
            item.metadata["workbook_provenance"]["content_revision"] = 999
        self.check_parity(0)

    def test_terminal_does_not_inherit_stale_analysis_eligibility(self):
        previous = self.service.evaluate_for_context(self.context)
        previous = replace(previous, research_question_assessments=tuple(
            replace(rq, information_need_assessments=tuple(
                replace(n, analysis_eligible=True) for n in rq.information_need_assessments
            )) for rq in previous.research_question_assessments
        ))
        for item in self.evidence.list_for_project("project"):
            item.metadata["normalized_numeric_value"] = "999999"
        terminal = self.service._finalize_terminal_readiness(self.context, previous)
        self.assertFalse(assessment(terminal).analysis_eligible)

    def test_snapshot_recovery_has_identical_decisions(self):
        result = self.service.evaluate_for_context(self.context)
        first = self.adapter.observe(NS())
        self.context.shared_state[ASSESSMENT] = {
            "fingerprint": first.fingerprint, "result": result.to_dict(),
        }
        restored = deepcopy(self.context.shared_state)
        self.context.shared_state.clear()
        self.context.shared_state.update(restored)
        second = self.adapter.observe(NS())
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(assessment(self.adapter.last_result).evidence_count, 3)

    def test_scope_resolution_is_shared_and_foreign_run_excluded(self):
        from application.authority_extension import build_composition, COMPOSED_AUTHORITY_KEY

        composition = build_composition(
            composition_id="composition", project_id="project", research_design_id="design",
            parent_source_workflow_run_id="run", member_workflow_run_ids=("run", "extension"),
            selected_information_need_ids=("in-pop",), created_at="2026-01-01",
        )
        repository = NS(get_by_id=lambda key: composition if key == "composition" else None)
        self.service._composed_authority_repository = repository
        self.context.write_shared(COMPOSED_AUTHORITY_KEY, {
            "composition_id": composition.composition_id,
            "composition_digest": composition.composition_digest,
        })
        first = self.evidence.list_for_project("project")[0]
        source = self.sources.get_by_id(first.source_id)
        self.sources.save(replace(source, workflow_run_refs=(*source.workflow_run_refs, "extension")),
                          expected_version=source.version)
        self.evidence.create(replace(first, id="extension-evidence", workflow_run_id="extension",
                                     deduplication_key="extension-evidence"))
        self.evidence.create(replace(first, id="foreign", workflow_run_id="foreign", deduplication_key="foreign"))
        self.check_parity(4)
        self.assertNotIn("foreign", {e.id for e in self.adapter.qualified()})
        with self.assertRaises(ValueError):
            self.context.shared_state[COMPOSED_AUTHORITY_KEY]["composition_digest"] = "wrong"
            self.adapter.observe(NS())

    def test_qualitative_reference_needs_no_numeric_locator(self):
        from domain.planning.evidence_nature import EvidenceNature
        design = self.context.workflow_template.research_design_snapshot
        numeric = design.information_needs[0]
        narrative = replace(numeric, id="qualitative", evidence_coverage=None,
                            evidence_expectation=replace(numeric.evidence_expectation,
                                nature=EvidenceNature.QUALITATIVE, requires_quantitative_evidence=False))
        updated = replace(design, information_needs=(numeric, narrative))
        self.context.workflow_template = replace(self.context.workflow_template, research_design_snapshot=updated)
        self.adapter.design = updated
        first = self.evidence.list_for_project("project")[0]
        item = replace(first, id="narrative", deduplication_key="narrative",
                       information_need_refs=("qualitative",),
                       metadata={"observation_period": first.metadata["observation_period"]})
        self.evidence.create(item)
        self.assertIn("narrative", {e.id for e in self.adapter.qualified()})

    def test_stale_assessment_is_noncurrent_while_missing_is_current(self):
        cold = self.check_parity(3)
        from application.research_quality.sufficiency_assessment_cache import SHARED_SUFFICIENCY_CACHE_KEY
        self.context.shared_state.pop(SHARED_SUFFICIENCY_CACHE_KEY, None)
        self.context.shared_state.pop(ASSESSMENT, None)
        self.adapter.observe(NS())
        self.assertFalse(assessment(self.adapter.last_result).assessment_current)
        for item in self.evidence.list_for_project("project"):
            item.metadata["normalized_numeric_value"] = "999999"
        self.context.shared_state.pop(ASSESSMENT, None)
        missing = self.adapter.observe(NS())
        self.assertEqual(assessment(self.adapter.last_result).evidence_count, 0)
        self.assertTrue(assessment(self.adapter.last_result).assessment_current)

    def test_extraction_gain_excludes_new_f1_rejected_evidence(self):
        from application.research_kernel.contracts import Action, OutcomeKind
        item = self.evidence.list_for_project("project")[0]
        bad_metadata = deepcopy(item.metadata)
        bad_metadata["normalized_numeric_value"] = "999999"
        rejected = replace(item, id="rejected-extra", deduplication_key="rejected-extra",
                           metadata=bad_metadata)
        diagnostics = NS(raw_candidates=1, failure_classification="", budget_stop=False,
                         extractor_failures=0, inner_calls_exception=0, dedup_hits=0, work_items=[])
        summary = NS(evidence_ids=("rejected-extra",), evidence_extracted=1,
                     extraction_failures=0, diagnostics=diagnostics)
        def extract(*args):
            self.evidence.create(rejected)
            return summary
        self.adapter.primitives.extract = extract
        self.adapter.items["extract-test"] = NS()
        action = Action("extract-test", "extract", "in-pop", "extract-test",
                        "untried_scoped_content", (), (), ("initial", "source"))
        with patch.object(self.adapter, "checkpoint"):
            outcome = self.adapter.execute(action)
        self.assertEqual(outcome.target_gain, 0)
        self.assertEqual(outcome.kind, OutcomeKind.REJECTED)
        self.assertNotIn("rejected-extra", {e.id for e in self.adapter.qualified()})
