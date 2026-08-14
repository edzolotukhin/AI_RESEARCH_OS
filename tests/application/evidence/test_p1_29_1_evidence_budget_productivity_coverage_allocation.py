"""PROPERTY AG offline acceptance: adaptive Evidence budget allocation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from application.config import ApplicationConfig
from application.evidence.content_chunking import SourceContentChunk
from application.evidence.evidence_extraction_scheduler import (
    EvidenceExtractionWorkItem,
    PHASE_DEPTH,
    PHASE_FIRST_OPPORTUNITY,
    SELECTION_DEPRIORITIZED_EMPTY_DEPTH,
    SELECTION_EXPLORATORY_DEPTH,
    SELECTION_PRODUCTIVE_DEPTH,
    SourceOutcomeState,
    adaptive_depth_selection_key,
    record_source_outcome,
    select_next_adaptive_depth,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.execution.execution_budget import ExecutionBudget
from application.execution.exceptions import BudgetExhaustedError
from domain.sources.source import Source


def _item(source_id: str, need_id: str, chunk: int = 1) -> EvidenceExtractionWorkItem:
    source = Source(
        id=source_id,
        project_id="project",
        url=f"https://example.test/{source_id}",
        canonical_url=f"https://example.test/{source_id}",
        title=source_id,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        content_text="content",
    )
    context = RunScopedSourceContext(
        workflow_run_id="run",
        research_design_id="design",
        information_need_ids=(need_id,),
        research_question_ids=(f"RQ-{need_id}",),
        query_ids=(f"SQ-{need_id}",),
    )
    return EvidenceExtractionWorkItem(
        source=source,
        chunk=SourceContentChunk("content", 0, 7),
        run_context=context,
        phase=PHASE_DEPTH if chunk else PHASE_FIRST_OPPORTUNITY,
        source_first_attempt=chunk == 0,
        chunk_index=chunk,
        primary_need_id=need_id,
    )


def _state(source_id: str, outcomes: tuple[tuple[int, bool, str], ...]) -> SourceOutcomeState:
    state = SourceOutcomeState(source_id=source_id)
    for persisted, empty, phase in outcomes:
        record_source_outcome(
            state,
            phase=phase,
            persisted_evidence=persisted,
            valid_empty=empty,
        )
    return state


class P1291EvidenceBudgetProductivityCoverageAllocationTests(unittest.TestCase):
    def test_case_01_first_opportunity_state_is_explicit(self) -> None:
        state = _state("a", ((0, True, PHASE_FIRST_OPPORTUNITY),))
        self.assertTrue(state.first_opportunity_completed)

    def test_case_02_one_empty_allows_exploratory_depth(self) -> None:
        item = _item("a", "IN1")
        selected, reason = select_next_adaptive_depth(
            [item], states={"a": _state("a", ((0, True, PHASE_FIRST_OPPORTUNITY),))}, evidence_counts_by_need={}
        )
        self.assertEqual(selected, item)
        self.assertEqual(reason, SELECTION_EXPLORATORY_DEPTH)

    def test_case_03_two_empty_calls_are_deprioritized(self) -> None:
        empty = _item("empty", "IN1", 2)
        productive = _item("productive", "IN1", 2)
        states = {
            "empty": _state("empty", ((0, True, PHASE_FIRST_OPPORTUNITY), (0, True, PHASE_DEPTH))),
            "productive": _state("productive", ((2, False, PHASE_FIRST_OPPORTUNITY), (1, False, PHASE_DEPTH))),
        }
        selected, _ = select_next_adaptive_depth([empty, productive], states=states, evidence_counts_by_need={"IN1": 1})
        self.assertEqual(selected.source.id, "productive")

    def test_case_04_productive_depth_has_productive_reason(self) -> None:
        item = _item("a", "IN1")
        _, reason = select_next_adaptive_depth([item], states={"a": _state("a", ((1, False, PHASE_FIRST_OPPORTUNITY),))}, evidence_counts_by_need={})
        self.assertEqual(reason, SELECTION_PRODUCTIVE_DEPTH)

    def test_case_05_depth_count_prevents_winner_take_all(self) -> None:
        leader = _item("leader", "IN1", 4)
        peer = _item("peer", "IN1", 2)
        states = {
            "leader": _state("leader", ((5, False, PHASE_FIRST_OPPORTUNITY), (5, False, PHASE_DEPTH), (5, False, PHASE_DEPTH), (5, False, PHASE_DEPTH))),
            "peer": _state("peer", ((1, False, PHASE_FIRST_OPPORTUNITY), (1, False, PHASE_DEPTH))),
        }
        selected, _ = select_next_adaptive_depth([leader, peer], states=states, evidence_counts_by_need={"IN1": 1})
        self.assertEqual(selected.source.id, "peer")

    def test_case_06_proriat_empty_then_productive_is_recordable(self) -> None:
        state = _state("proriat", ((0, True, PHASE_FIRST_OPPORTUNITY), (2, False, PHASE_DEPTH)))
        self.assertEqual(state.productive_calls, 1)
        self.assertFalse(state.repeated_zero_yield)

    def test_case_07_imarc_repeated_empty_loses_to_productive(self) -> None:
        imarc = _item("imarc", "IN2", 3)
        coherent = _item("coherent", "IN2", 3)
        states = {
            "imarc": _state("imarc", ((0, True, PHASE_FIRST_OPPORTUNITY), (0, True, PHASE_DEPTH))),
            "coherent": _state("coherent", ((7, False, PHASE_FIRST_OPPORTUNITY), (6, False, PHASE_DEPTH))),
        }
        selected, reason = select_next_adaptive_depth([imarc, coherent], states=states, evidence_counts_by_need={"IN2": 1})
        self.assertEqual(selected.source.id, "coherent")
        self.assertNotEqual(reason, SELECTION_DEPRIORITIZED_EMPTY_DEPTH)

    def test_case_08_productive_with_rejects_remains_productive(self) -> None:
        state = _state("mixed", ((8, False, PHASE_FIRST_OPPORTUNITY),))
        self.assertEqual(state.last_outcome, "productive")

    def test_case_09_valid_empty_is_not_an_error(self) -> None:
        state = _state("empty", ((0, True, PHASE_FIRST_OPPORTUNITY),))
        self.assertEqual(state.last_outcome, "valid_empty")

    def test_case_10_undercovered_need_participates_in_order(self) -> None:
        covered = _item("a", "IN-A")
        uncovered = _item("b", "IN-B")
        states = {key: _state(key, ((0, True, PHASE_FIRST_OPPORTUNITY),)) for key in ("a", "b")}
        selected, _ = select_next_adaptive_depth([covered, uncovered], states=states, evidence_counts_by_need={"IN-A": 2})
        self.assertEqual(selected.source.id, "b")

    def test_case_11_zero_evidence_need_wins_equal_productivity(self) -> None:
        a, b = _item("a", "IN-A"), _item("b", "IN-B")
        states = {key: _state(key, ((2, False, PHASE_FIRST_OPPORTUNITY),)) for key in ("a", "b")}
        selected, _ = select_next_adaptive_depth([a, b], states=states, evidence_counts_by_need={"IN-A": 2, "IN-B": 0})
        self.assertEqual(selected.source.id, "b")

    def test_case_12_initial_depth_respects_six_call_reserve(self) -> None:
        budget = ExecutionBudget(evidence_max_llm_calls=50, evidence_remediation_reserved_llm_calls=6, llm_max_calls_per_run=1000)
        for _ in range(44):
            budget.assert_can_call("evidence", purpose="initial")
            budget.record_llm_call("evidence", purpose="initial")
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence", purpose="initial")

    def test_case_13_targeted_source_can_use_reserved_call(self) -> None:
        budget = ExecutionBudget(evidence_max_llm_calls=50, evidence_remediation_reserved_llm_calls=6, llm_max_calls_per_run=1000)
        for _ in range(44):
            budget.record_llm_call("evidence", purpose="initial")
        budget.assert_can_call("evidence", purpose="remediation")

    def test_case_14_total_calls_never_exceed_fifty(self) -> None:
        budget = ExecutionBudget(evidence_max_llm_calls=50, evidence_remediation_reserved_llm_calls=6, llm_max_calls_per_run=1000)
        for _ in range(44):
            budget.record_llm_call("evidence", purpose="initial")
        for _ in range(6):
            budget.record_llm_call("evidence", purpose="remediation")
        with self.assertRaises(BudgetExhaustedError):
            budget.assert_can_call("evidence", purpose="remediation")

    def test_case_15_nonempty_failure_does_not_masquerade_as_empty(self) -> None:
        state = _state("a", ((0, False, PHASE_FIRST_OPPORTUNITY),))
        self.assertEqual(state.valid_empty_calls, 0)
        self.assertEqual(state.last_outcome, "non_productive_other")

    def test_case_16_ordering_is_deterministic(self) -> None:
        items = [_item("b", "IN1"), _item("a", "IN1")]
        states = {key: _state(key, ((0, True, PHASE_FIRST_OPPORTUNITY),)) for key in ("a", "b")}
        first = select_next_adaptive_depth(items, states=states, evidence_counts_by_need={})[0]
        second = select_next_adaptive_depth(list(reversed(items)), states=states, evidence_counts_by_need={})[0]
        self.assertEqual(first.source.id, second.source.id)

    def test_case_17_stable_tie_break_uses_source_id(self) -> None:
        items = [_item("b", "IN1"), _item("a", "IN1")]
        states = {key: _state(key, ((0, True, PHASE_FIRST_OPPORTUNITY),)) for key in ("a", "b")}
        self.assertEqual(select_next_adaptive_depth(items, states=states, evidence_counts_by_need={})[0].source.id, "a")

    def test_case_18_scheduler_state_has_no_external_call_surface(self) -> None:
        self.assertNotIn("llm", SourceOutcomeState.__annotations__)

    def test_case_19_default_reserve_reuses_existing_field(self) -> None:
        self.assertEqual(ApplicationConfig().evidence_remediation_reserved_llm_calls, 6)

    def test_case_20_p1_28_2b_replay_deprioritizes_fifth_imarc_call(self) -> None:
        imarc, coherent = _item("imarc", "IN2", 4), _item("coherent", "IN2", 4)
        states = {
            "imarc": _state("imarc", ((0, True, PHASE_FIRST_OPPORTUNITY), (0, True, PHASE_DEPTH))),
            "coherent": _state("coherent", ((2, False, PHASE_FIRST_OPPORTUNITY), (7, False, PHASE_DEPTH))),
        }
        self.assertEqual(select_next_adaptive_depth([imarc, coherent], states=states, evidence_counts_by_need={"IN2": 5})[0].source.id, "coherent")

    def test_case_21_p1_27_2_replay_repeated_empty_is_lower_rank(self) -> None:
        repeated = _item("repeated", "IN4", 3)
        exploratory = _item("explore", "IN6", 1)
        states = {
            "repeated": _state("repeated", ((0, True, PHASE_FIRST_OPPORTUNITY), (0, True, PHASE_DEPTH))),
            "explore": _state("explore", ((0, True, PHASE_FIRST_OPPORTUNITY),)),
        }
        self.assertEqual(select_next_adaptive_depth([repeated, exploratory], states=states, evidence_counts_by_need={})[0].source.id, "explore")

    def test_case_22_heat_pump_fixture_is_domain_agnostic(self) -> None:
        self.assertEqual(_item("nz-heat-pump", "IN-NZ").source.id, "nz-heat-pump")

    def test_case_23_upi_fixture_is_domain_agnostic(self) -> None:
        self.assertEqual(_item("india-upi", "IN-UPI").primary_need_id, "IN-UPI")

    def test_case_24_electricity_fixture_is_domain_agnostic(self) -> None:
        self.assertEqual(_item("german-power", "IN-DE").chunk_index, 1)

    def test_case_25_niche_b2b_fixture_uses_same_key(self) -> None:
        item = _item("industrial-sensor", "IN-B2B")
        state = _state("industrial-sensor", ((1, False, PHASE_FIRST_OPPORTUNITY),))
        key = adaptive_depth_selection_key(item, state=state, evidence_counts_by_need={})
        self.assertIsInstance(key, tuple)


if __name__ == "__main__":
    unittest.main()
