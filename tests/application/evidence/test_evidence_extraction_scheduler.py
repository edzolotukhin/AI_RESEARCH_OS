"""Tests for need-fair evidence extraction scheduling."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.content_chunking import split_normalized_source_content
from application.evidence.evidence_extraction_scheduler import (
    build_need_fair_extraction_queue,
)


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ResearchQuestion(id="rq-2", question="Q2", objective_refs=()),
            ResearchQuestion(id="rq-3", question="Q3", objective_refs=()),
        ),
        information_needs=(
            InformationNeed(id="IN1", research_question_id="rq-1", description="Need 1"),
            InformationNeed(id="IN2", research_question_id="rq-2", description="Need 2"),
            InformationNeed(id="IN3", research_question_id="rq-3", description="Need 3"),
        ),
    )


def _source(
    source_id: str,
    *,
    need_id: str,
    rq_id: str,
    run_id: str = "run-1",
    content: str,
) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id=source_id,
        project_id="project-1",
        url=f"https://example.com/{source_id}",
        canonical_url=f"https://example.com/{source_id}",
        title=source_id,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum=f"checksum-{source_id}",
        workflow_run_refs=(run_id,),
        research_design_refs=("design-1",),
        information_need_refs=(need_id,),
        research_question_refs=(rq_id,),
        query_refs=(f"sq-{need_id}",),
        metadata={
            "discovery_records": [
                {
                    "workflow_run_id": run_id,
                    "research_design_id": "design-1",
                    "query_id": f"sq-{need_id}",
                    "information_need_id": need_id,
                    "research_question_id": rq_id,
                }
            ]
        },
        retrieved_at=now,
        version=1,
    )


class EvidenceExtractionSchedulerTests(unittest.TestCase):
    def test_round_robin_interleaves_first_chunks_across_needs(self) -> None:
        design = _design()
        chunk_chars = 40
        overlap = 0
        big_content = "A" * 120
        sources = [
            _source("source-in1", need_id="IN1", rq_id="rq-1", content=big_content),
            _source("source-in2", need_id="IN2", rq_id="rq-2", content=big_content),
            _source("source-in3", need_id="IN3", rq_id="rq-3", content=big_content),
        ]

        queue = build_need_fair_extraction_queue(
            sources,
            design=design,
            workflow_run_id="run-1",
            research_design_id="design-1",
            chunk_chars=chunk_chars,
            overlap_chars=overlap,
        )

        first_pass_needs = [
            item.run_context.information_need_ids[0]
            for item in queue[:3]
        ]
        self.assertEqual(first_pass_needs, ["IN1", "IN2", "IN3"])

    def test_queue_is_deterministic(self) -> None:
        design = _design()
        sources = [
            _source("b-source", need_id="IN2", rq_id="rq-2", content="B" * 120),
            _source("a-source", need_id="IN1", rq_id="rq-1", content="A" * 120),
        ]
        kwargs = dict(
            design=design,
            workflow_run_id="run-1",
            research_design_id="design-1",
            chunk_chars=40,
            overlap_chars=0,
        )
        first = build_need_fair_extraction_queue(sources, **kwargs)
        second = build_need_fair_extraction_queue(list(reversed(sources)), **kwargs)
        self.assertEqual(
            [item.source.id for item in first],
            [item.source.id for item in second],
        )

    def test_large_source_does_not_front_load_all_chunks_before_other_needs(self) -> None:
        design = _design()
        queue = build_need_fair_extraction_queue(
            [
                _source("large-in1", need_id="IN1", rq_id="rq-1", content="X" * 200),
                _source("small-in2", need_id="IN2", rq_id="rq-2", content="Y" * 10),
            ],
            design=design,
            workflow_run_id="run-1",
            research_design_id="design-1",
            chunk_chars=50,
            overlap_chars=0,
        )
        first_two_needs = [
            item.run_context.information_need_ids[0] for item in queue[:2]
        ]
        self.assertEqual(first_two_needs, ["IN1", "IN2"])


if __name__ == "__main__":
    unittest.main()
