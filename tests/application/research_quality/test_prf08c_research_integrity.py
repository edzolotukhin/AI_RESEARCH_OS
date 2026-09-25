"""PRF-08C offline reproduction; no network or paid provider calls."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.ports.evidence_ports import EvidenceCandidate
from application.evidence.temporal_scope import (
    exact_observation_cutoff,
    observation_eligibility,
    qualifying_evidence,
)
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)
from application.sources.search_query_builder import SearchQueryBuilder
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.research_quality.raw_semantic_decision import RawSemanticDecision
from domain.research_quality.sufficiency_policy import apply_sufficiency_policy
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.research_brief import ResearchBrief
from domain.sources.source import Source


def _design(topic: str = "public charging") -> ResearchDesign:
    return ResearchDesign(
        id="offline-design",
        research_questions=(ResearchQuestion(id="RQ1", question=f"How has {topic} changed?"),),
        information_needs=tuple(
            InformationNeed(
                id=f"IN{index}", research_question_id="RQ1",
                description=f"Document {topic} measure {index}",
                timeframe="1 January 2025 to 1 July 2026", geography="United Kingdom",
            ) for index in range(1, 4)
        ),
    )


def _brief(*, market: str = "publicly accessible charging stations for electric vehicles") -> ResearchBrief:
    return ResearchBrief(
        title="UK public rapid charging infrastructure retail opportunity evidence review",
        business_question=(
            "What changed in public rapid charging infrastructure for retail "
            "opportunity evidence review? Exclude presented "
            "observations, unsupported ROI/market-share claims."
        ),
        market=market,
        timeframe="1 January 2025 to 1 July 2026; sources available by 25 September 2026",
        geography=("United Kingdom",),
    )


def _evidence(
    evidence_id: str, source_id: str, period: str | None,
    *, origin: str | None = None, excerpt: str | None = None,
    need: str = "IN1",
) -> Evidence:
    metadata = {}
    if period:
        metadata["observation_period"] = period
    if origin:
        metadata["data_lineage"] = {"status": "established", "origin_id": origin}
    return Evidence(
        id=evidence_id, project_id="synthetic-project", source_id=source_id,
        source_content_checksum="offline", workflow_run_id="synthetic-run",
        research_design_id="offline-design", statement=f"Fact {evidence_id}",
        source_excerpt=excerpt or f"Observed {period or 'at an unspecified date'}.",
        created_at="2026-09-25T00:00:00Z", information_need_refs=(need,),
        research_question_refs=("RQ1",), metadata=metadata,
    )


class SearchIntegrityTests(unittest.TestCase):
    def test_exclusion_words_cannot_become_category_subject(self) -> None:
        query = SearchQueryBuilder().build_queries(_design(), brief=_brief())[0]
        self.assertIn("charging", query.provider_query_text.casefold())
        self.assertNotIn("unsupported roi", query.provider_query_text.casefold())
        self.assertNotIn("presented observations", query.provider_query_text.casefold())
        self.assertEqual(query.information_need_id, "IN1")
        self.assertEqual(query.research_question_id, "RQ1")

    def test_second_run_cannot_inherit_first_run_exclusions(self) -> None:
        builder = SearchQueryBuilder()
        builder.build_queries(_design(), brief=_brief())
        second = ResearchBrief(
            title="Residential heat pumps", market="residential heat pumps",
            business_question="What is the installed heat pump stock?",
            geography=("United Kingdom",), timeframe="2025",
        )
        query = builder.build_queries(_design("heat pumps"), brief=second)[0]
        self.assertIn("heat pumps", query.provider_query_text.casefold())
        self.assertNotIn("roi", query.provider_query_text.casefold())

    def test_legitimate_roi_is_not_blacklisted(self) -> None:
        brief = ResearchBrief(
            title="ROI of warehouse automation", market="warehouse automation",
            business_question="What is the ROI of warehouse automation?",
            geography=("United Kingdom",),
        )
        query = SearchQueryBuilder().build_queries(_design("ROI of warehouse automation"), brief=brief)[0]
        self.assertIn("roi", query.provider_query_text.casefold())


class TemporalIntegrityTests(unittest.TestCase):
    def test_exact_cutoff_is_structured_from_frozen_brief(self) -> None:
        self.assertEqual(str(exact_observation_cutoff(_brief())), "2026-07-01")

    def test_publication_date_does_not_determine_observation_eligibility(self) -> None:
        cutoff = exact_observation_cutoff(_brief())
        scenarios = (
            ("June 2026", "eligible"),
            ("1 June 2026", "eligible"),
            ("August 2026", "out_of_period"),
            ("Q3 2026", "out_of_period"),
            ("2026", "out_of_period"),
            ("June 2026 to August 2026", "out_of_period"),
            (None, "unknown"),
        )
        for index, (period, expected) in enumerate(scenarios):
            with self.subTest(period=period):
                item = _evidence(str(index), "source", period)
                self.assertEqual(observation_eligibility(item, cutoff), expected)

    def test_unanchored_model_period_cannot_qualify(self) -> None:
        item = _evidence("one", "source", "June 2026", excerpt="No observation date supplied")
        self.assertEqual(observation_eligibility(item, exact_observation_cutoff(_brief())), "unknown")

    def test_forecast_not_direct_observed_evidence(self) -> None:
        item = _evidence("one", "source", "June 2026", excerpt="Forecast for June 2026")
        self.assertEqual(observation_eligibility(item, exact_observation_cutoff(_brief())), "unknown")


class ExtractedProvenanceTests(unittest.TestCase):
    def _persist(self, metadata: dict) -> Evidence:
        repo = Mock()
        repo.get_by_deduplication_key.return_value = None
        source = Source(
            id="source-one", project_id="synthetic-project",
            url="https://example.test/report", canonical_url="https://example.test/report",
            title="Synthetic report", retrieved_at="2026-09-25T00:00:00Z",
            content_text="As at 1 July 2026, the count was 25. Data collated by SampleData.",
            content_checksum="test-checksum",
        )
        candidate = EvidenceCandidate(
            statement="The count was 25 at the cutoff.",
            source_excerpt="As at 1 July 2026, the count was 25.",
            evidence_type="direct_excerpt", research_question_refs=("RQ1",),
            information_need_refs=("IN1",), metadata=metadata,
        )
        service = EvidenceExtractionService(
            evidence_extractor=Mock(), evidence_repository=repo,
            source_repository=Mock(),
        )
        service._persist_candidate(
            candidate=candidate, source=source, project_id="synthetic-project",
            workflow_run_id="synthetic-run", research_design_id="offline-design",
        )
        return repo.create.call_args.args[0]

    def test_grounded_period_and_data_origin_persist(self) -> None:
        item = self._persist({
            "observation_period": "1 July 2026", "data_origin_id": "SampleData",
            "data_origin_excerpt": "Data collated by SampleData.",
        })
        self.assertEqual(item.metadata["observation_period"], "1 July 2026")
        self.assertEqual(item.metadata["data_lineage"]["origin_id"], "SampleData")

    def test_ungrounded_period_and_data_origin_do_not_persist(self) -> None:
        item = self._persist({
            "observation_period": "August 2026", "data_origin_id": "FabricatedOrg",
            "data_origin_excerpt": "Data collated by FabricatedOrg.",
        })
        self.assertNotIn("observation_period", item.metadata)
        self.assertNotIn("data_lineage", item.metadata)


class IntegratedFailurePatternTests(unittest.TestCase):
    def test_shared_feed_post_cutoff_and_missing_needs_block_readiness(self) -> None:
        design, brief = _design(), _brief()
        evidence = (
            _evidence("official", "official-document", "1 July 2026", origin="specialist-feed"),
            _evidence("specialist", "specialist-document", "June 2026", origin="specialist-feed"),
            _evidence("late", "specialist-document", "August 2026", origin="specialist-feed"),
        )
        eligible = qualifying_evidence(design=design, evidence=evidence, brief=brief)
        self.assertEqual({item.id for item in eligible}, {"official", "specialist"})
        signals = DeterministicSufficiencyEvaluator().evaluate(design=design, evidence=eligible)
        self.assertEqual(signals[0].evidence_count, 2)
        self.assertEqual(signals[0].independent_source_count, 1)
        self.assertEqual([item.evidence_count for item in signals], [2, 0, 0])
        readiness = DeterministicResearchSufficiencyEvaluator().evaluate(design=design, evidence=eligible)
        self.assertFalse(readiness.ready_for_analysis)

    def test_shared_origin_cannot_satisfy_two_source_policy(self) -> None:
        expectation = EvidenceExpectation(
            nature=EvidenceNature.QUANTITATIVE,
            required_aspects=("market_value",), minimum_independent_sources=2,
        )
        original = _design()
        need = replace(original.information_needs[0], evidence_expectation=expectation)
        design = replace(original, information_needs=(need, *original.information_needs[1:]))
        evidence = (
            _evidence("official", "official-document", "1 July 2026", origin="feed"),
            _evidence("provider", "provider-document", "1 July 2026", origin="feed"),
        )
        signals = DeterministicSufficiencyEvaluator().evaluate(design=design, evidence=evidence)[0]
        self.assertEqual(signals.independent_source_count, 1)
        policy = apply_sufficiency_policy(
            information_need=need, evidence_expectation=expectation, signals=signals,
            raw_semantic=RawSemanticDecision(
                supported_aspects=("market_value",), missing_aspects=(),
                semantic_conflicts=(), confidence=0.9, reason="Synthetic coverage",
            ),
        )
        self.assertNotEqual(policy.status, SufficiencyStatus.SUFFICIENT)


class SufficiencyCacheIntegrityTests(unittest.TestCase):
    def test_lineage_or_observation_change_invalidates_cached_assessment(self) -> None:
        design = _design()
        need, question = design.information_needs[0], design.research_questions[0]
        original = _evidence("same-id", "same-source", "1 July 2026")

        def fingerprint(item: Evidence) -> str:
            return build_sufficiency_assessment_fingerprint(
                information_need=need, research_question=question,
                evidence_ids=(item.id,), evidence_by_id={item.id: item},
                max_evidence_items=10,
            )

        changed_period = replace(
            original, metadata={**original.metadata, "observation_period": "August 2026"},
        )
        changed_lineage = replace(
            original, metadata={**original.metadata, "data_lineage": {
                "status": "established", "origin_id": "independent-survey",
            }},
        )
        self.assertNotEqual(fingerprint(original), fingerprint(changed_period))
        self.assertNotEqual(fingerprint(original), fingerprint(changed_lineage))


if __name__ == "__main__":
    unittest.main()
