"""Real adapter nonempty outcomes retain canonical validation and readiness."""
import json
import unittest
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from application.research_kernel.controller import Controller
from application.research_kernel.contracts import OutcomeKind, Stop
from domain.ai.llm_response import LLMResponse
from tests.application.test_ark02_desk import fixture
from tests.application.test_ark02_kernel import Store
from tests.application.test_ark02_desk import Search, Retriever
from dataclasses import replace


class DeskIntegrityTests(unittest.TestCase):
    def late_replay(self, cross_only):
        config, context, _, evidence, llm, adapter, _, _ = fixture()
        # This variant explicitly has a second viable attempt for the remaining
        # target; per-gap=1 correctly forbids that even with a global spare slot.
        if cross_only:
            config = replace(config, targeted_max_attempts_per_gap=2, research_max_gap_rounds_per_run=2)
            adapter.config = config
        class SharedSearch(Search):
            def search(self, query):
                return [replace(c, url=f"https://example.test/shared/{i}") for i, c in enumerate(super().search(query))]
        class LongRetriever(Retriever):
            def retrieve(self, candidate):
                source = super().retrieve(candidate)
                return replace(source, content_text=("Irrigation meter definitions. " + candidate.url + " ") * 1000)
        adapter.primitives.acquisition._search_provider.delegate = SharedSearch()
        adapter.primitives.acquisition._source_retriever.delegate = LongRetriever()
        def generate(prompt, *, options=None):
            llm.calls += 1
            refs = () if llm.calls <= 6 else ("in-1",) if cross_only and llm.calls == 7 else ("in-0", "in-1")
            return LLMResponse(content=json.dumps({"items": [{"information_need_id": ref,
                "statement": "Irrigation meter definitions.", "source_excerpt": "Irrigation meter definitions."}
                for ref in refs]}), finish_reason="stop")
        llm.generate = generate
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
            adapter.finish(result)
        return result, context, evidence, llm

    def test_all_gaps_close_at_seventh_real_extraction(self):
        result, context, _, llm = self.late_replay(False)
        self.assertEqual(llm.calls, 7)
        self.assertEqual(result.terminal, Stop.READY)
        self.assertTrue(context.shared_state["research_readiness"]["ready_for_analysis"])

    def test_cross_only_seventh_does_not_discard_last_real_slot(self):
        result, context, evidence, llm = self.late_replay(True)
        extractions = [d for d in result.decisions if d["action"].startswith("extract:")]
        self.assertEqual(extractions[6]["outcome"], OutcomeKind.CROSS.value)
        self.assertEqual(extractions[6]["target_gain"], 0)
        self.assertEqual(llm.calls, 8)
        self.assertTrue(evidence.list_for_project(context.project.id))
        self.assertEqual(result.used["extractions"], 8)

    def execute(self, *, unrelated=False, assessments=True):
        config, context, _, evidence, llm, adapter, _, _ = fixture()
        def generate(prompt, *, options=None):
            llm.calls += 1
            # Read only the authoritative needs enumerated by the normal prompt.
            refs = [n.id for n in adapter.design.information_needs if n.id in prompt.user]
            text = "Collectible certificates have high value." if unrelated else "Irrigation meter definitions."
            return LLMResponse(content=json.dumps({"items": [{"information_need_id": refs[0],
                "statement": text, "source_excerpt": text}]}), finish_reason="stop")
        llm.generate = generate
        initial = adapter.initial_state()
        if not assessments:
            initial.limits["assessments"] = 0
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(initial)
            adapter.finish(result)
        return result, context, evidence, llm

    def test_productive_evidence_is_reconciled_before_canonical_assessment(self):
        result, context, evidence, llm = self.execute()
        self.assertTrue(evidence.list_for_project(context.project.id))
        self.assertIn(OutcomeKind.TARGET, [o.kind for o in result.completed.values()])
        self.assertTrue(any(d["action"].startswith("assess:") for d in result.decisions))
        self.assertNotEqual(result.terminal, Stop.RECONCILIATION)
        self.assertLessEqual(llm.calls, 8)

    def test_unrelated_and_ungrounded_output_cannot_make_ready(self):
        result, context, evidence, llm = self.execute(unrelated=True)
        self.assertFalse(evidence.list_for_project(context.project.id))
        self.assertFalse(context.shared_state["research_readiness"]["ready_for_analysis"])
        self.assertIn(OutcomeKind.REJECTED, [o.kind for o in result.completed.values()])
        self.assertLessEqual(llm.calls, 8)

    def test_no_assessment_budget_retains_evidence_but_refuses_readiness(self):
        result, context, evidence, _ = self.execute(assessments=False)
        self.assertTrue(evidence.list_for_project(context.project.id))
        self.assertFalse(context.shared_state["research_readiness"]["ready_for_analysis"])
        self.assertNotEqual(result.terminal, Stop.READY)


if __name__ == "__main__":
    unittest.main()
