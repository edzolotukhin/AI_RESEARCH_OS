"""Offline regressions for bounded cross-need source coverage."""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from application.sources.deterministic_source_relevance import (
    ELIGIBILITY_DIRECT,
    ELIGIBILITY_PROXY,
    build_relevance_context,
    evaluate_candidate,
)
from application.sources.source_acquisition_service import (
    SourceAcquisitionService,
    _CandidateGroup,
    _PendingCandidate,
)
from application.sources.source_budget import SourceAcquisitionBudget
from application.ports.source_ports import SourceRetriever
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever


def _design(count: int = 3) -> ResearchDesign:
    return ResearchDesign(
        id="design-offline",
        research_questions=tuple(
            ResearchQuestion(id=f"RQ{index}", question=f"Question {index}")
            for index in range(1, count + 1)
        ),
        information_needs=tuple(
            InformationNeed(
                id=f"IN{index}", research_question_id=f"RQ{index}",
                description=f"Evidence for question {index}",
            )
            for index in range(1, count + 1)
        ),
    )


def _pending(need_id: str, url: str, *, title: str = "Candidate") -> _PendingCandidate:
    return _PendingCandidate(
        candidate=SourceCandidate(
            provider="offline", url=url, title=title, snippet="Relevant context",
            query_id=f"query-{need_id}", rank=1,
        ),
        query=SearchQuery(
            id=f"query-{need_id}", research_question_id=f"RQ{need_id[2:]}",
            information_need_id=need_id, query_text="synthetic research",
        ),
        canonical_url=url,
    )


class _OfflineRetriever(SourceRetriever):
    def __init__(self, failed: frozenset[str] = frozenset()) -> None:
        self.failed = failed
        self.fetched: list[str] = []

    def retrieve(self, candidate: SourceCandidate) -> Source:
        self.fetched.append(candidate.url)
        failed = candidate.url in self.failed
        return Source(
            id="", project_id="", url=candidate.url,
            canonical_url=candidate.url, title=candidate.title,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=(RetrievalStatus.FAILED if failed else RetrievalStatus.ACQUIRED),
            content_type="text/html" if not failed else "",
            content_text="Synthetic text" if not failed else "",
            metadata={"failure_category": "timeout"} if failed else {},
        )


def _service(retriever: SourceRetriever, *, cap: int = 3) -> SourceAcquisitionService:
    return SourceAcquisitionService(
        search_provider=Mock(), source_retriever=retriever,
        source_repository=InMemorySourceRepository(),
        budget=SourceAcquisitionBudget(
            max_sources_per_run=cap, min_successful_sources=1,
            min_information_need_coverage_ratio=1.0,
        ),
    )


def _acquire(service: SourceAcquisitionService, need_urls: list[tuple[str, str]],
             *, design: ResearchDesign | None = None):
    design = design or _design()
    groups = [
        _CandidateGroup(canonical_url=url, items=[_pending(need_id, url)])
        for need_id, url in need_urls
    ]
    return service._acquire_candidates(
        project_id="offline-project", workflow_run_id="offline-run",
        research_design_id=design.id, design=design, groups=groups,
        started_at=time.monotonic(),
    )


class Prf08gCoverageTests(unittest.TestCase):
    def test_competing_needs_get_one_attempt_before_duplicate_coverage(self) -> None:
        retriever = _OfflineRetriever()
        result = _acquire(_service(retriever), [
            ("IN1", "https://example.org/first"),
            ("IN1", "https://example.org/duplicate-coverage"),
            ("IN2", "https://example.org/second"),
            ("IN3", "https://example.org/third"),
        ])
        self.assertEqual(retriever.fetched, [
            "https://example.org/first", "https://example.org/second",
            "https://example.org/third",
        ])
        self.assertEqual(result[4], 3)  # actual fetch attempts, unchanged cap
        self.assertEqual(result[11], {"IN1", "IN2", "IN3"})
        self.assertEqual(result[6], 1)  # duplicate-coverage candidate skipped

    def test_failed_need_gets_viable_fallback_within_same_cap(self) -> None:
        failed = "https://example.org/failed"
        retriever = _OfflineRetriever(frozenset({failed}))
        result = _acquire(_service(retriever), [
            ("IN1", failed),
            ("IN2", "https://example.org/second"),
            ("IN2", "https://example.org/repeat-second"),
            ("IN1", "https://example.org/fallback"),
        ], design=_design(2))
        self.assertEqual(retriever.fetched, [
            failed, "https://example.org/second", "https://example.org/fallback",
        ])
        self.assertEqual(result[2], 1)  # failed fetch is recorded, not forgiven
        self.assertEqual(result[4], 3)
        self.assertEqual(result[11], {"IN1", "IN2"})

    def test_canonical_tracking_variants_do_not_consume_two_slots(self) -> None:
        query = SearchQuery(
            id="query-IN1", research_question_id="RQ1",
            information_need_id="IN1", query_text="synthetic research",
        )
        first = _pending("IN1", "https://example.org/page?utm_source=one")
        second = _pending("IN1", "https://example.org/page")
        provider = Mock()
        provider.search.return_value = [first.candidate, second.candidate]
        service = SourceAcquisitionService(
            search_provider=provider, source_retriever=_OfflineRetriever(),
            source_repository=InMemorySourceRepository(),
            budget=SourceAcquisitionBudget(max_sources_per_run=1),
        )
        raw, grouped = service._collect_candidates([query])
        self.assertEqual(raw, 2)
        self.assertEqual(list(grouped), ["https://example.org/page"])
        self.assertEqual(len(grouped["https://example.org/page"]), 2)

    def test_current_http_retriever_screens_known_unreadable_pdf(self) -> None:
        service = _service(HttpSourceRetriever())
        pdf = "https://example.org/report.PDF?download=1"
        html = "https://example.org/report.html"
        grouped = {
            pdf: [_pending("IN1", pdf)],
            html: [_pending("IN1", html)],
        }
        eligible, decisions, skipped, _ = service._select_groups(
            grouped, design=_design(1), exhausted_pairs=frozenset(),
        )
        self.assertEqual([item.canonical_url for item in eligible], [html])
        self.assertEqual(skipped, 1)
        self.assertTrue(any(
            item.get("reason") == "retriever_known_unsupported_url"
            for item in decisions
        ))
        self.assertFalse(HttpSourceRetriever().known_unsupported_url(html))

    def test_foreign_titled_candidate_is_not_direct_for_requested_geography(self) -> None:
        need = InformationNeed(
            id="IN1", research_question_id="RQ1",
            description="Electric vehicle charger utilization by region",
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.MIXED, geography="United Kingdom",
                required_aspects=("utilization_metric_definition",),
            ),
        )
        design = ResearchDesign(
            id="geo-design",
            research_questions=(ResearchQuestion(
                id="RQ1", question="How are electric vehicle chargers used by region?",
            ),),
            information_needs=(need,),
        )
        context = build_relevance_context(design, need)
        foreign = SourceCandidate(
            provider="offline", url="https://example.org/foreign-report",
            title="China electric vehicle charger utilization report",
            snippet="United Kingdom charging utilization statistics are mentioned comparatively",
            query_id="query-IN1", rank=1,
        )
        local = SourceCandidate(
            provider="offline", url="https://example.org/local-report",
            title="United Kingdom electric vehicle charger utilization report",
            snippet="Regional charging utilization method and scope",
            query_id="query-IN1", rank=2,
        )
        foreign_decision = evaluate_candidate(context, foreign)
        local_decision = evaluate_candidate(context, local)
        self.assertEqual(foreign_decision.eligibility, ELIGIBILITY_PROXY)
        self.assertEqual(foreign_decision.reason, "conflicting_title_geography")
        self.assertEqual(local_decision.eligibility, ELIGIBILITY_DIRECT)


if __name__ == "__main__":
    unittest.main()
