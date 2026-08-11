"""P1-12 official-statistics-aware source selection — offline acceptance."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from application.sources.deterministic_source_relevance import (
    ELIGIBILITY_DIRECT,
    build_relevance_context,
    evaluate_candidate,
    selection_sort_key,
)
from application.sources.source_acquisition_service import (
    SourceAcquisitionService,
    _CandidateGroup,
    _PendingCandidate,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate
from application.sources.source_budget import SourceAcquisitionBudget
from unittest.mock import Mock

REPO = Path(__file__).resolve().parents[3]
P1_10_TERMINAL = REPO / "artifacts" / "acceptance" / "p1_10_live_terminal.json"
SOURCE_CAP = 30


def _quant_ee(**overrides) -> EvidenceExpectation:
    payload = {
        "nature": EvidenceNature.QUANTITATIVE,
        "required_aspects": (
            "annual_installations",
            "geographic_coverage",
            "data_source_authority",
        ),
        "geography": "England and Wales",
        "timeframe": "2022-2025",
        "requires_quantitative_evidence": True,
        "minimum_independent_sources": 2,
    }
    payload.update(overrides)
    return EvidenceExpectation(**payload)


def _heat_pump_design(*, extra_needs: tuple[InformationNeed, ...] = ()) -> ResearchDesign:
    needs = (
        InformationNeed(
            id="IN1",
            research_question_id="RQ1",
            description=(
                "Annual residential heat-pump installation counts for England "
                "and Wales, 2022-2025"
            ),
            priority=1,
            preferred_source_types=(
                "official statistics",
                "regulator/government",
                "industry associations",
            ),
            geography="England and Wales",
            timeframe="2022-2025",
            evidence_expectation=_quant_ee(),
        ),
        InformationNeed(
            id="IN5",
            research_question_id="RQ2",
            description="Publicly documented national heat-pump policy incentives",
            priority=2,
            preferred_source_types=("regulator/government",),
            geography="England and Wales",
            timeframe="2022-2025",
            evidence_expectation=EvidenceExpectation(
                nature=EvidenceNature.QUALITATIVE,
                required_aspects=("policy_name", "measure_description"),
                geography="England and Wales",
                timeframe="2022-2025",
                requires_quantitative_evidence=False,
            ),
        ),
    ) + extra_needs
    return ResearchDesign(
        id="design-p1-12",
        research_questions=(
            ResearchQuestion(
                id="RQ1",
                question=(
                    "What are publicly reported residential heat-pump installation "
                    "levels and trends in England and Wales for 2022-2025?"
                ),
                objective_refs=("Quantify adoption trends",),
                priority=1,
            ),
            ResearchQuestion(
                id="RQ2",
                question="Which national policy incentives affected heat-pump uptake?",
                objective_refs=("Identify policy incentives",),
                priority=2,
            ),
        ),
        information_needs=needs,
    )


def _candidate(
    *,
    url: str,
    title: str,
    snippet: str = "",
    rank: int = 5,
    query_id: str = "q1",
) -> SourceCandidate:
    return SourceCandidate(
        provider="fixture",
        url=url,
        title=title,
        snippet=snippet,
        query_id=query_id,
        rank=rank,
    )


def _query(need_id: str, query_id: str = "q1") -> SearchQuery:
    return SearchQuery(
        id=query_id,
        research_question_id="RQ1",
        information_need_id=need_id,
        query_text="heat pump installations",
    )


def _sort_urls(
    design: ResearchDesign,
    rows: list[tuple[str, str, str, str, int]],
) -> list[str]:
    """rows: (url, title, snippet, need_id, provider_rank) → ordered canonical URLs."""
    grouped: dict[str, list[_PendingCandidate]] = {}
    for url, title, snippet, need_id, rank in rows:
        pending = _PendingCandidate(
            candidate=_candidate(url=url, title=title, snippet=snippet, rank=rank),
            query=_query(need_id),
            canonical_url=url,
        )
        grouped.setdefault(url, []).append(pending)
    service = SourceAcquisitionService(
        search_provider=Mock(),
        source_retriever=Mock(),
        source_repository=Mock(),
        budget=SourceAcquisitionBudget(max_sources_per_run=SOURCE_CAP),
    )
    eligible, _, _, _ = service._select_groups(
        grouped,
        design=design,
        exhausted_pairs=frozenset(),
    )
    return [group.canonical_url for group in eligible]


class P112OfficialStatisticsSelectionTests(unittest.TestCase):
    def test_a_official_stats_outrank_generic_blog_for_quantitative_need(self) -> None:
        design = _heat_pump_design()
        ordered = _sort_urls(
            design,
            [
                (
                    "https://blog.example/heat-pump-guide",
                    "Complete heat pump guide for homeowners England Wales",
                    "Tips for residential heat pump installation and uptake trends",
                    "IN1",
                    1,
                ),
                (
                    "https://assets.example.gov.uk/media/Heat_pump_deployment_quarterly_statistics_2025_Q4.xlsx",
                    "Heat pump deployment quarterly statistics United Kingdom 2025 Q4",
                    "Official quarterly statistics for heat pump deployment",
                    "IN1",
                    5,
                ),
            ],
        )
        self.assertEqual(
            ordered[0],
            "https://assets.example.gov.uk/media/Heat_pump_deployment_quarterly_statistics_2025_Q4.xlsx",
        )

    def test_b_official_but_topically_irrelevant_does_not_gain_blind_authority(self) -> None:
        design = _heat_pump_design()
        ordered = _sort_urls(
            design,
            [
                (
                    "https://www.example.gov.uk/statistics/bus-passenger-journeys",
                    "Bus passenger journey statistics England",
                    "National statistics on public bus transport demand",
                    "IN1",
                    1,
                ),
                (
                    "https://vendor.example/heat-pump-installations-by-region-2026",
                    "UK heat pump installations by region 2026",
                    "Residential heat pump installation counts by region",
                    "IN1",
                    4,
                ),
            ],
        )
        self.assertEqual(
            ordered[0],
            "https://vendor.example/heat-pump-installations-by-region-2026",
        )

    def test_c_relevant_non_government_primary_stats_can_rank_high(self) -> None:
        design = _heat_pump_design()
        ctx = build_relevance_context(design, design.information_needs[0])
        decision = evaluate_candidate(
            ctx,
            _candidate(
                url="https://standards.example.org/low-carbon/mcs-data-dashboard",
                title="MCS data dashboard heat pump installations",
                snippet="Certification body dashboard of certified heat pump installations",
            ),
            canonical_url="https://standards.example.org/low-carbon/mcs-data-dashboard",
        )
        self.assertGreater(decision.statistics_signal, 0)
        self.assertGreater(decision.expectation_boost, 0)
        self.assertNotEqual(decision.eligibility, "ineligible")

    def test_d_generic_blog_with_statistics_lexeme_does_not_beat_official_stats(self) -> None:
        design = _heat_pump_design()
        ordered = _sort_urls(
            design,
            [
                (
                    "https://homefacts.example/post/heat-pump-statistics-facts-updated",
                    "Heat pump statistics facts updated May 2025",
                    "Blog summary of heat pump statistics and facts",
                    "IN1",
                    1,
                ),
                (
                    "https://www.example.gov.uk/government/collections/boiler-upgrade-scheme-statistics",
                    "Boiler Upgrade Scheme heat pump grant statistics England Wales",
                    "Official statistics collection for Boiler Upgrade Scheme heat pump grants",
                    "IN1",
                    5,
                ),
            ],
        )
        self.assertEqual(
            ordered[0],
            "https://www.example.gov.uk/government/collections/boiler-upgrade-scheme-statistics",
        )

    def test_e_multiple_ins_remain_represented_under_cap(self) -> None:
        extra = tuple(
            InformationNeed(
                id=f"IN{n}",
                research_question_id="RQ1",
                description=f"Heat pump need {n} installations geography England",
                preferred_source_types=("official statistics",),
                geography="England",
                timeframe="2022-2025",
                evidence_expectation=_quant_ee(
                    required_aspects=(f"aspect_{n}", "geographic_coverage"),
                ),
            )
            for n in range(2, 6)
        )
        design = _heat_pump_design(extra_needs=extra)
        rows: list[tuple[str, str, str, str, int]] = []
        for need in design.information_needs:
            nid = need.id
            rows.append(
                (
                    f"https://www.example.gov.uk/statistics/heat-pump-{nid.lower()}",
                    f"Heat pump installations statistics {nid}",
                    f"Official heat pump installations statistics for {nid}",
                    nid,
                    3,
                )
            )
            rows.append(
                (
                    f"https://blog.example/{nid.lower()}-tips",
                    f"Heat pump tips {nid} England Wales",
                    f"Generic heat pump blog for {nid}",
                    nid,
                    1,
                )
            )
        ordered = _sort_urls(design, rows)
        selected = set(ordered[:SOURCE_CAP])
        represented = {
            need.id
            for need in design.information_needs
            if any(need.id.lower() in url for url in selected)
        }
        self.assertGreaterEqual(len(represented), 3)

    def test_f_below_cap_preserves_all_eligible(self) -> None:
        design = _heat_pump_design()
        rows = [
            (
                f"https://site{i}.example/heat-pump-installations",
                f"Heat pump installations England {i}",
                "Residential heat pump installations",
                "IN1",
                i,
            )
            for i in range(5)
        ]
        ordered = _sort_urls(design, rows)
        self.assertEqual(len(ordered), 5)

    def test_g_deterministic_identical_inputs(self) -> None:
        design = _heat_pump_design()
        rows = [
            (
                "https://blog.example/heat-pump-guide",
                "Heat pump guide England Wales",
                "Residential heat pump guide",
                "IN1",
                2,
            ),
            (
                "https://www.example.gov.uk/statistics/heat-pump-deployment",
                "Heat pump deployment statistics",
                "Official heat pump deployment statistics",
                "IN1",
                4,
            ),
        ]
        first = _sort_urls(design, rows)
        second = _sort_urls(design, list(reversed(rows)))
        self.assertEqual(first, second)

    def test_expectation_boost_zero_without_topic_alignment(self) -> None:
        design = _heat_pump_design()
        ctx = build_relevance_context(design, design.information_needs[0])
        decision = evaluate_candidate(
            ctx,
            _candidate(
                url="https://www.example.gov.uk/statistics/rail-freight",
                title="Rail freight statistics",
                snippet="Official rail freight statistics bulletin",
            ),
            canonical_url="https://www.example.gov.uk/statistics/rail-freight",
        )
        self.assertEqual(decision.expectation_boost, 0)

    def test_selection_sort_key_orders_boost_before_topic_score(self) -> None:
        low_topic_high_boost = type(
            "D",
            (),
            {
                "tier_rank": 3,
                "expectation_boost": 100,
                "topic_score": 10,
                "geo_penalty": 0,
            },
        )()
        high_topic_no_boost = type(
            "D",
            (),
            {
                "tier_rank": 3,
                "expectation_boost": 0,
                "topic_score": 40,
                "geo_penalty": 0,
            },
        )()
        key_a = selection_sort_key(
            decision=low_topic_high_boost,  # type: ignore[arg-type]
            need_coverage=1,
            best_rank=5,
            canonical_url="a",
        )
        key_b = selection_sort_key(
            decision=high_topic_no_boost,  # type: ignore[arg-type]
            need_coverage=1,
            best_rank=1,
            canonical_url="b",
        )
        self.assertLess(key_a, key_b)


class P112P10ReplayTests(unittest.TestCase):
    """Replay P1-10 candidate URLs offline against the new selector."""

    @classmethod
    def setUpClass(cls) -> None:
        if not P1_10_TERMINAL.exists():
            raise unittest.SkipTest("P1-10 terminal artifact not present")
        cls.terminal = json.loads(P1_10_TERMINAL.read_text(encoding="utf-8"))
        cls.design_payload = cls.terminal["workflow"]["research_design"]
        cls.design = ResearchDesign.from_dict(
            {
                **cls.design_payload,
                "id": cls.design_payload.get("id") or "p1-10-design",
            }
        )
        assert cls.design is not None
        results = cls.terminal["results_first"]
        sa = None
        for task in results["task_results"]:
            shared = (task.get("snapshot") or {}).get("shared_state") or {}
            if "source_acquisition" in shared:
                sa = shared["source_acquisition"]
                break
        assert sa is not None
        cls.decisions = list(sa.get("selection_decisions") or [])

    def _old_attempt_order(self) -> list[str]:
        return [
            d["canonical_url"]
            for d in self.decisions
            if d.get("action")
            in {"selected", "fetch_failed", "proxy_deprioritized", "skipped_budget"}
        ]

    def _new_order(self) -> list[str]:
        # Fixture titles for skipped_budget rows that lack original title/snippet
        # metadata in selection_decisions (observability gap). Not product logic.
        title_hints = {
            "Heat_pump_deployment_quarterly_statistics": (
                "Heat pump deployment quarterly statistics United Kingdom 2025 Q4"
            ),
            "boiler-upgrade-scheme-statistics": (
                "Boiler Upgrade Scheme statistics collection official"
            ),
            "mcs-data-dashboard": (
                "MCS data dashboard certified heat pump installations"
            ),
        }

        def _title_for(url: str) -> str:
            for needle, title in title_hints.items():
                if needle in url:
                    return title
            return url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")

        def _need_for(url: str, fallback: str | None) -> str:
            if fallback:
                return fallback
            if "boiler-upgrade" in url:
                return "IN2"
            if "mcs-data" in url:
                return "IN4"
            return "IN1"

        rows: list[tuple[str, str, str, str, int]] = []
        seen: set[str] = set()
        for decision in self.decisions:
            url = decision.get("canonical_url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            need_id = _need_for(url, decision.get("information_need_id"))
            title = _title_for(url)
            rows.append(
                (
                    url,
                    title,
                    title,
                    need_id,
                    int(decision.get("provider_rank") or 9),
                )
            )
        return _sort_urls(self.design, rows)

    def test_defect_reproduced_old_order_skipped_official_stats(self) -> None:
        old = self._old_attempt_order()
        # First 30 attempted in original run; remainder skipped_budget.
        attempted = set(old[:SOURCE_CAP])
        desnz = next(
            url
            for url in old
            if "Heat_pump_deployment_quarterly_statistics" in url
        )
        bus = next(
            url for url in old if "boiler-upgrade-scheme-statistics" in url
        )
        mcs = next(url for url in old if "mcs-data-dashboard" in url)
        self.assertNotIn(desnz, attempted)
        self.assertNotIn(bus, attempted)
        self.assertNotIn(mcs, attempted)

    def test_fix_includes_official_stats_inside_cap(self) -> None:
        new_order = self._new_order()
        selected = set(new_order[:SOURCE_CAP])
        desnz = next(
            url
            for url in new_order
            if "Heat_pump_deployment_quarterly_statistics" in url
        )
        bus = next(
            url for url in new_order if "boiler-upgrade-scheme-statistics" in url
        )
        mcs = next(url for url in new_order if "mcs-data-dashboard" in url)
        self.assertIn(desnz, selected)
        self.assertIn(bus, selected)
        self.assertIn(mcs, selected)
        self.assertLess(new_order.index(desnz), SOURCE_CAP)
        self.assertLess(new_order.index(bus), SOURCE_CAP)
        self.assertLess(new_order.index(mcs), SOURCE_CAP)


if __name__ == "__main__":
    unittest.main()
