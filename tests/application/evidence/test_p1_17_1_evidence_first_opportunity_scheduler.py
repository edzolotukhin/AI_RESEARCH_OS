"""P1-17.1 coverage-before-depth Evidence extraction scheduling tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.config import ApplicationConfig
from application.evidence.evidence_extraction_scheduler import (
    EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH,
    PHASE_DEPTH,
    PHASE_FIRST_OPPORTUNITY,
    build_need_fair_extraction_queue,
)
from application.execution.execution_budget import ExecutionBudget


def _design(*need_ids: str) -> ResearchDesign:
    if not need_ids:
        need_ids = ("IN1", "IN2", "IN3")
    questions = tuple(
        ResearchQuestion(id=f"rq-{i}", question=f"Q{i}", objective_refs=())
        for i in range(1, len(need_ids) + 1)
    )
    needs = tuple(
        InformationNeed(
            id=need_id,
            research_question_id=questions[index].id,
            description=f"Need {need_id}",
        )
        for index, need_id in enumerate(need_ids)
    )
    return ResearchDesign(
        id="design-1",
        research_questions=questions,
        information_needs=needs,
    )


def _source(
    source_id: str,
    *,
    need_id: str,
    content: str,
    run_id: str = "run-1",
    design_id: str = "design-1",
    rq_id: str | None = None,
    canonical_url: str | None = None,
    retrieval_status: RetrievalStatus = RetrievalStatus.ACQUIRED,
) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    resolved_rq = rq_id or "rq-1"
    url = canonical_url or f"https://example.com/{source_id}"
    return Source(
        id=source_id,
        project_id="project-1",
        url=url,
        canonical_url=url,
        title=source_id,
        retrieval_status=retrieval_status,
        content_text=content,
        content_checksum=f"checksum-{source_id}",
        content_type="text/html",
        workflow_run_refs=(run_id,),
        research_design_refs=(design_id,),
        information_need_refs=(need_id,),
        research_question_refs=(resolved_rq,),
        query_refs=(f"sq-{need_id}",),
        metadata={
            "discovery_records": [
                {
                    "workflow_run_id": run_id,
                    "research_design_id": design_id,
                    "query_id": f"sq-{need_id}",
                    "information_need_id": need_id,
                    "research_question_id": resolved_rq,
                }
            ]
        },
        retrieved_at=now,
        version=1,
    )


def _queue(sources: list[Source], design: ResearchDesign, *, chunk_chars: int = 40, overlap: int = 0):
    return build_need_fair_extraction_queue(
        sources,
        design=design,
        workflow_run_id="run-1",
        research_design_id="design-1",
        chunk_chars=chunk_chars,
        overlap_chars=overlap,
    )


class P1171EvidenceFirstOpportunitySchedulerTests(unittest.TestCase):
    def test_case_01_three_sources_each_get_one_attempt_under_budget_three(self) -> None:
        design = _design("IN1", "IN2", "IN3")
        content = "X" * 120
        sources = [
            _source("source-a", need_id="IN1", content=content, rq_id="rq-1"),
            _source("source-b", need_id="IN2", content=content, rq_id="rq-2"),
            _source("source-c", need_id="IN3", content=content, rq_id="rq-3"),
        ]
        queue = _queue(sources, design)
        first_three = queue[:3]
        self.assertEqual({item.phase for item in first_three}, {PHASE_FIRST_OPPORTUNITY})
        self.assertEqual({item.source.id for item in first_three}, {"source-a", "source-b", "source-c"})
        self.assertTrue(all(item.source_first_attempt for item in first_three))

    def test_case_02_old_depth_starvation_replaced_by_abc_first(self) -> None:
        design = _design("IN1")
        # Old behavior would spend A0,A1,A2 before B/C. New: A0,B0,C0 first.
        sources = [
            _source("source-a", need_id="IN1", content="A" * 120, rq_id="rq-1"),
            _source("source-b", need_id="IN1", content="B" * 120, rq_id="rq-1"),
            _source("source-c", need_id="IN1", content="C" * 120, rq_id="rq-1"),
        ]
        queue = _queue(sources, design)
        self.assertEqual(
            [item.source.id for item in queue[:3]],
            ["source-a", "source-b", "source-c"],
        )
        self.assertTrue(all(item.phase == PHASE_FIRST_OPPORTUNITY for item in queue[:3]))

    def test_case_03_depth_resumes_after_first_opportunity(self) -> None:
        design = _design("IN1", "IN2")
        sources = [
            _source("source-a", need_id="IN1", content="A" * 120, rq_id="rq-1"),
            _source("source-b", need_id="IN2", content="B" * 120, rq_id="rq-2"),
        ]
        queue = _queue(sources, design)
        phase1 = [item for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY]
        phase2 = [item for item in queue if item.phase == PHASE_DEPTH]
        self.assertEqual(len(phase1), 2)
        self.assertGreaterEqual(len(phase2), 2)
        self.assertTrue(all(item.chunk_index == 0 for item in phase1))
        self.assertTrue(all(item.chunk_index >= 1 for item in phase2))
        # Depth begins only after all first opportunities.
        first_depth_index = next(i for i, item in enumerate(queue) if item.phase == PHASE_DEPTH)
        self.assertTrue(all(item.phase == PHASE_FIRST_OPPORTUNITY for item in queue[:first_depth_index]))

    def test_case_04_single_source_equivalent_to_document_depth(self) -> None:
        design = _design("IN1")
        source = _source("only", need_id="IN1", content="Z" * 120, rq_id="rq-1")
        queue = _queue([source], design)
        self.assertEqual([item.source.id for item in queue], ["only"] * len(queue))
        self.assertEqual(queue[0].phase, PHASE_FIRST_OPPORTUNITY)
        self.assertTrue(all(item.phase == PHASE_DEPTH for item in queue[1:]))
        self.assertEqual([item.chunk_index for item in queue], list(range(len(queue))))

    def test_case_05_single_chunk_source_has_no_depth_entry(self) -> None:
        design = _design("IN1")
        source = _source("short", need_id="IN1", content="short", rq_id="rq-1")
        queue = _queue([source], design, chunk_chars=40)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].phase, PHASE_FIRST_OPPORTUNITY)
        self.assertEqual(queue[0].chunk_index, 0)

    def test_case_06_duplicate_canonical_source_one_first_opportunity(self) -> None:
        design = _design("IN1", "IN2")
        shared = "https://example.com/shared"
        sources = [
            _source("src-dup-a", need_id="IN1", content="A" * 80, rq_id="rq-1", canonical_url=shared),
            _source("src-dup-b", need_id="IN2", content="B" * 80, rq_id="rq-2", canonical_url=shared),
        ]
        queue = _queue(sources, design)
        phase1 = [item for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY]
        self.assertEqual(len(phase1), 1)
        self.assertEqual(phase1[0].source.id, "src-dup-a")

    def test_case_07_multi_need_source_one_source_level_first_opportunity(self) -> None:
        design = _design("IN1", "IN2")
        now = datetime.now(timezone.utc).isoformat()
        source = Source(
            id="multi",
            project_id="project-1",
            url="https://example.com/multi",
            canonical_url="https://example.com/multi",
            title="multi",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="M" * 120,
            content_checksum="checksum-multi",
            workflow_run_refs=("run-1",),
            research_design_refs=("design-1",),
            information_need_refs=("IN1", "IN2"),
            research_question_refs=("rq-1", "rq-2"),
            query_refs=("sq-IN1", "sq-IN2"),
            metadata={
                "discovery_records": [
                    {
                        "workflow_run_id": "run-1",
                        "research_design_id": "design-1",
                        "query_id": "sq-IN1",
                        "information_need_id": "IN1",
                        "research_question_id": "rq-1",
                    },
                    {
                        "workflow_run_id": "run-1",
                        "research_design_id": "design-1",
                        "query_id": "sq-IN2",
                        "information_need_id": "IN2",
                        "research_question_id": "rq-2",
                    },
                ]
            },
            retrieved_at=now,
            version=1,
        )
        queue = _queue([source], design)
        phase1 = [item for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY]
        self.assertEqual(len(phase1), 1)
        self.assertEqual(phase1[0].primary_need_id, "IN1")

    def test_case_08_failed_or_empty_content_not_scheduled(self) -> None:
        design = _design("IN1", "IN2")
        sources = [
            _source("ok", need_id="IN1", content="OK content here", rq_id="rq-1"),
            _source("empty", need_id="IN2", content="   ", rq_id="rq-2"),
            _source(
                "failed",
                need_id="IN2",
                content="should not matter",
                rq_id="rq-2",
                retrieval_status=RetrievalStatus.FAILED,
            ),
        ]
        # Scheduler does not filter retrieval_status (service eligibility does),
        # but empty content must be excluded here.
        queue = _queue(sources, design)
        ids = {item.source.id for item in queue}
        self.assertIn("ok", ids)
        self.assertNotIn("empty", ids)
        # Failed with content would still be queued if passed in; eligibility is service-side.
        # Ensure empty is the hard scheduler exclusion for content.
        empty_only = _queue(
            [_source("empty2", need_id="IN1", content="", rq_id="rq-1")],
            design,
        )
        self.assertEqual(empty_only, [])

    def test_case_09_more_sources_than_budget_deterministic_prefix(self) -> None:
        design = _design("IN1")
        sources = [
            _source(f"source-{i:02d}", need_id="IN1", content="Z" * 10, rq_id="rq-1")
            for i in range(10)
        ]
        queue = _queue(sources, design)
        # Budget of 3 would attempt first three first-opportunity items only.
        prefix = queue[:3]
        self.assertEqual(len(prefix), 3)
        self.assertTrue(all(item.phase == PHASE_FIRST_OPPORTUNITY for item in prefix))
        self.assertEqual(
            [item.source.id for item in prefix],
            ["source-00", "source-01", "source-02"],
        )

    def test_case_10_zero_yield_does_not_create_second_phase1_slot(self) -> None:
        design = _design("IN1", "IN2")
        sources = [
            _source("source-a", need_id="IN1", content="A" * 80, rq_id="rq-1"),
            _source("source-b", need_id="IN2", content="B" * 80, rq_id="rq-2"),
        ]
        queue = _queue(sources, design)
        phase1_for_a = [
            item for item in queue
            if item.source.id == "source-a" and item.phase == PHASE_FIRST_OPPORTUNITY
        ]
        self.assertEqual(len(phase1_for_a), 1)

    def test_case_11_need_fair_first_opportunities_across_ins(self) -> None:
        design = _design("IN1", "IN2", "IN3")
        sources = [
            _source("s-in1", need_id="IN1", content="A" * 80, rq_id="rq-1"),
            _source("s-in2", need_id="IN2", content="B" * 80, rq_id="rq-2"),
            _source("s-in3", need_id="IN3", content="C" * 80, rq_id="rq-3"),
        ]
        queue = _queue(sources, design)
        self.assertEqual(
            [item.primary_need_id for item in queue[:3]],
            ["IN1", "IN2", "IN3"],
        )

    def test_case_12_later_in_source_not_starved_by_early_depth(self) -> None:
        design = _design("IN1", "IN9")
        sources = [
            _source("early-long", need_id="IN1", content="E" * 200, rq_id="rq-1"),
            _source("late-in9", need_id="IN9", content="L" * 40, rq_id="rq-1"),
        ]
        queue = _queue(sources, design, chunk_chars=40)
        first_ids = [item.source.id for item in queue[:2]]
        self.assertEqual(set(first_ids), {"early-long", "late-in9"})
        self.assertTrue(all(item.phase == PHASE_FIRST_OPPORTUNITY for item in queue[:2]))

    def test_case_13_html_and_xlsx_format_neutral(self) -> None:
        from dataclasses import replace

        design = _design("IN1", "IN2")
        html = _source("html-src", need_id="IN1", content="H" * 80, rq_id="rq-1")
        xlsx = replace(
            _source("xlsx-src", need_id="IN2", content="X" * 80, rq_id="rq-2"),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={
                "discovery_records": [
                    {
                        "workflow_run_id": "run-1",
                        "research_design_id": "design-1",
                        "query_id": "sq-IN2",
                        "information_need_id": "IN2",
                        "research_question_id": "rq-2",
                    }
                ],
                "parser": "xlsx",
            },
        )
        queue = _queue([html, xlsx], design)
        phase1_ids = [item.source.id for item in queue if item.phase == PHASE_FIRST_OPPORTUNITY]
        self.assertEqual(set(phase1_ids), {"html-src", "xlsx-src"})

    def test_case_14_p1_16_topology_desnz_like_before_call_39(self) -> None:
        """
        Replay the P1-16 failure shape:
        - many acquired sources with varied chunk counts
        - DESNZ-like source mapped to IN9
        - old need-fair depth would place it at ordinal 44 (>39)
        - new coverage-before-depth must place first opportunity before 39
        """
        need_ids = ("IN1", "IN2", "IN4", "IN5", "IN7", "IN8", "IN9", "IN12")
        design = _design(*need_ids)
        # Approximate P1-16 topology: large IN1/IN9 depth pools + DESNZ under IN9.
        sources = [
            _source("21634578-fed9-4110-bae5-5c7664f10498", need_id="IN1", content="A" * 16000, rq_id="rq-1"),
            _source("a3f9136a-ab97-4465-bbad-cc73ce7308be", need_id="IN12", content="B" * 21000, rq_id="rq-1"),
            _source("288af5ac-5a43-4246-8a52-4c01079670eb", need_id="IN2", content="C" * 17000, rq_id="rq-1"),
            _source("3f2be809-e81b-4b2f-9fe0-959c44b80adc", need_id="IN4", content="D" * 18000, rq_id="rq-1"),
            _source("2b35e124-6796-4526-a33d-efa9b0635776", need_id="IN5", content="E" * 16000, rq_id="rq-1"),
            _source("14de33c0-f11f-4dea-9c4a-3c277f39a904", need_id="IN7", content="F" * 200, rq_id="rq-1"),
            _source("8c047485-e529-4b28-a7db-5150729a8e61", need_id="IN8", content="G" * 13000, rq_id="rq-1"),
            _source("39d105e2-21f5-410f-ad13-d6bf25a1a18f", need_id="IN9", content="H" * 66000, rq_id="rq-1"),
            _source("881878ad-754f-4d4f-8560-84e733bc6440", need_id="IN1", content="I" * 52000, rq_id="rq-1"),
            _source("dcc7d56f-0bc6-4781-81f4-4f765b1246f6", need_id="IN8", content="J" * 32000, rq_id="rq-1"),
            _source("757c515b-f849-4e4e-a587-25937e45b009", need_id="IN2", content="K" * 11000, rq_id="rq-1"),
            _source("d9e67428-dab4-4a0e-8fdd-5ffad47d312b", need_id="IN2", content="L" * 17000, rq_id="rq-1"),
            _source("9d2c2c4a-86a5-40d9-9328-a7530368da70", need_id="IN1", content="M" * 8000, rq_id="rq-1"),
            _source("cabb268f-9b6e-48f1-9d32-e9355f777bf2", need_id="IN1", content="N" * 25000, rq_id="rq-1"),
            _source(
                "74ea7efd-2473-47e4-96df-cdb423e6bee8",
                need_id="IN9",
                content="O" * 48990,
                rq_id="rq-1",
            ),
        ]
        queue = build_need_fair_extraction_queue(
            sources,
            design=design,
            workflow_run_id="run-1",
            research_design_id="design-1",
            chunk_chars=8000,
            overlap_chars=500,
        )
        desnz_id = "74ea7efd-2473-47e4-96df-cdb423e6bee8"
        desnz_first = next(i for i, item in enumerate(queue) if item.source.id == desnz_id)
        self.assertLess(desnz_first, 39)
        self.assertEqual(queue[desnz_first].phase, PHASE_FIRST_OPPORTUNITY)
        self.assertTrue(queue[desnz_first].source_first_attempt)
        # All first opportunities precede any depth for that source.
        self.assertEqual(queue[desnz_first].chunk_index, 0)

    def test_case_15_evidence_cap_unchanged(self) -> None:
        # Stock default remains 50; Construction of ExecutionBudget uses the same constant.
        budget = ExecutionBudget()
        self.assertEqual(budget.evidence_max_llm_calls, 50)
        self.assertEqual(ApplicationConfig().evidence_max_llm_calls, 50)

    def test_case_16_global_and_downstream_reserve_unchanged(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=50,
            sufficiency_max_llm_calls=20,
            analysis_max_llm_calls=14,
            report_max_llm_calls=20,
            review_max_llm_calls=7,
            llm_max_calls_per_run=100,
        )
        self.assertEqual(budget.llm_max_calls_per_run, 100)
        self.assertEqual(budget.evidence_max_llm_calls, 50)
        # Initial evidence reserve still S+A+R+V => 61 => allowed 39
        reserve = budget._downstream_reserve_required("evidence", purpose=None)
        self.assertEqual(reserve, 61)

    def test_case_17_depth_order_need_fair_after_phase1(self) -> None:
        design = _design("IN1", "IN2")
        sources = [
            _source("a-in1", need_id="IN1", content="A" * 120, rq_id="rq-1"),
            _source("b-in2", need_id="IN2", content="B" * 120, rq_id="rq-2"),
        ]
        queue = _queue(sources, design)
        depth = [item for item in queue if item.phase == PHASE_DEPTH]
        # Need-fair depth interleaves remaining chunks across needs.
        self.assertEqual(
            [item.primary_need_id for item in depth[:2]],
            ["IN1", "IN2"],
        )

    def test_case_18_work_item_still_source_times_chunk(self) -> None:
        design = _design("IN1")
        queue = _queue(
            [_source("only", need_id="IN1", content="Z" * 120, rq_id="rq-1")],
            design,
        )
        for item in queue:
            self.assertTrue(item.chunk.text)
            self.assertEqual(item.source.id, "only")
            self.assertIsNotNone(item.run_context)

    def test_case_19_targeted_single_source_queue_still_sensible(self) -> None:
        design = _design("IN2")
        source = _source("targeted", need_id="IN2", content="T" * 120, rq_id="rq-2")
        queue = _queue([source], design)
        self.assertGreaterEqual(len(queue), 1)
        self.assertEqual(queue[0].phase, PHASE_FIRST_OPPORTUNITY)
        self.assertEqual(queue[0].source.id, "targeted")

    def test_case_20_scheduler_is_pure_no_llm_side_effect(self) -> None:
        design = _design("IN1")
        source = _source("pure", need_id="IN1", content="P" * 40, rq_id="rq-1")
        # Building the queue must not touch ExecutionBudget / LLM.
        queue1 = _queue([source], design)
        queue2 = _queue([source], design)
        self.assertEqual(
            [(i.source.id, i.chunk_index, i.phase) for i in queue1],
            [(i.source.id, i.chunk_index, i.phase) for i in queue2],
        )
        self.assertEqual(EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH, "coverage_before_depth_need_fair")


if __name__ == "__main__":
    unittest.main()
