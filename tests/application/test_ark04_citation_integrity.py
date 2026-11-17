"""Offline citation contract and actual Desk continuation regression."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from hashlib import sha256
from types import SimpleNamespace
import unittest

from application.evidence.citation_integrity import citation_is_valid
from application.evidence.grounding import normalize_source_text, verify_grounding
from application.evidence.temporal_scope import (
    exact_observation_cutoff,
    normalize_observation_period,
    observation_interval,
    observation_eligibility,
    qualify_evidence_with_temporal_decisions,
    qualifying_evidence,
)
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from application.research_kernel.controller import Controller
from domain.planning.research_design import ResearchDesign
from tests.application.test_ark02_desk import fixture
from tests.application.test_ark02_kernel import Store


def pair(text="Prefix. Citation text. End.", excerpt="Citation text."):
    source = SimpleNamespace(id="source", project_id="project", content_text=text,
        content_checksum=sha256(text.encode()).hexdigest())
    item = SimpleNamespace(id="evidence", source_id=source.id, project_id=source.project_id,
        source_content_checksum=source.content_checksum, source_excerpt=excerpt,
        source_locator=verify_grounding(source_text=text, excerpt=excerpt).to_dict(),
        information_need_refs=("in",))
    return item, source


class LegacyObservationPeriodRegressionTests(unittest.TestCase):
    # Synthetic grounded fixtures use the four observed production spellings.
    # These tests establish Temporal eligibility, not numeric sufficiency.
    periods = ("2018 01-01", "2017 01-01", "2019 01-01", "2016 12-01")

    def setUp(self):
        from domain.planning.research_design import InformationNeed, ResearchQuestion
        from domain.planning.evidence_expectation import EvidenceExpectation
        from domain.planning.evidence_nature import EvidenceNature
        from domain.research_brief import ResearchBrief
        self.design = ResearchDesign(
            id="offline-design",
            research_questions=(ResearchQuestion("RQ1", "Annual population observations?"),),
            information_needs=(InformationNeed(
                id="IN1", research_question_id="RQ1",
                description="Annual population observations",
                evidence_expectation=EvidenceExpectation(
                    nature=EvidenceNature.QUANTITATIVE,
                    requires_quantitative_evidence=True,
                ),
            ),),
        )
        self.brief = ResearchBrief(
            title="Synthetic annual series", business_question="Annual population observations?",
            timeframe="2015–2021",
        )

    def fact(self, period, *, identifier="fact", excerpt=None, metadata=None):
        from tests.application.research_quality.test_prf08c_research_integrity import _evidence
        item = _evidence(
            identifier, "source", period,
            excerpt=excerpt or f"Population recorded on {period} was 100.",
        )
        return replace(item, metadata=metadata) if metadata is not None else item

    def qualify(self, items):
        from tests.helpers.citation_fixtures import sources_for
        sources = sources_for(items)
        self.assertTrue(all(citation_is_valid(e, sources.get_by_id(e.source_id)) for e in items))
        before = deepcopy(items)
        decisions = qualify_evidence_with_temporal_decisions(
            design=self.design, evidence=items, brief=self.brief,
            source_repository=sources,
        )
        compatible = qualifying_evidence(
            design=self.design, evidence=items, brief=self.brief,
            source_repository=sources,
        )
        self.assertEqual(compatible, decisions.evidence)
        self.assertEqual(items, before)
        return decisions

    def test_four_grounded_legacy_periods_qualify_in_frozen_year_interval(self):
        self.assertIsNone(exact_observation_cutoff(self.brief))
        self.assertEqual(observation_interval(self.brief.timeframe),
                         (date(2015, 1, 1), date(2021, 12, 31)))
        items = tuple(self.fact(p, identifier=f"dated-{i}") for i, p in enumerate(self.periods))
        result = self.qualify(items)
        self.assertEqual(len(result.evidence), 4)
        self.assertEqual(set(result.decisions.values()), {"applicable_satisfied"})
        for period in self.periods:
            with self.subTest(period=period):
                expected = date.fromisoformat(period.replace(" ", "-"))
                self.assertEqual(observation_interval(period), (expected, expected))

    def test_four_dated_and_four_missing_periods_remain_distinct(self):
        dated = tuple(self.fact(p, identifier=f"dated-{i}") for i, p in enumerate(self.periods))
        missing = tuple(self.fact(None, identifier=f"missing-{i}",
                                  excerpt="Population observations have no stated date.")
                        for i in range(4))
        result = self.qualify(dated + missing)
        self.assertEqual({e.id for e in result.evidence}, {e.id for e in dated})
        for item in dated:
            self.assertEqual(result.decisions[(item.id, "IN1")], "applicable_satisfied")
        for item in missing:
            self.assertEqual(result.decisions[(item.id, "IN1")], "applicable_unresolved")

    def test_invalid_legacy_calendar_dates_remain_unresolved(self):
        for period in ("2017 02-29", "2018 02-30", "2019 04-31", "2018 13-01", "2018 01-00"):
            with self.subTest(period=period):
                self.assertIsNone(observation_interval(period))
                result = self.qualify((self.fact(period),))
                self.assertFalse(result.evidence)
                self.assertEqual(result.decisions[("fact", "IN1")], "applicable_unresolved")

    def test_normalization_does_not_authorize_ungrounded_or_mismatched_period(self):
        scenarios = (
            ("Population recorded on 2017 01-01 was 100.",
             {"observation_period": "2018 01-01"}),
            ("Population recorded on 2017 01-01 was 100.",
             {"observation_period": "2018-01-01", "observation_period_source": "2017 01-01"}),
            ("Population recorded on 2018 01-01 was 100.",
             {"observation_period": "2018-01-01", "observation_period_source": "2017 01-01"}),
        )
        for excerpt, metadata in scenarios:
            with self.subTest(metadata=metadata):
                result = self.qualify((self.fact(None, excerpt=excerpt, metadata=metadata),))
                self.assertFalse(result.evidence)
                self.assertEqual(result.decisions[("fact", "IN1")], "applicable_unresolved")

    def test_legacy_publication_and_forecast_periods_remain_unresolved(self):
        for excerpt in ("Published on 2018 01-01. Population observations unavailable.",
                        "Forecast population for 2018 01-01 was 100."):
            for normalized in (False, True):
                with self.subTest(excerpt=excerpt, normalized=normalized):
                    metadata = {"observation_period": "2018 01-01"}
                    if normalized:
                        metadata.update(observation_period="2018-01-01",
                                        observation_period_source="2018 01-01")
                    result = self.qualify((self.fact(None, excerpt=excerpt, metadata=metadata),))
                    self.assertFalse(result.evidence)
                    self.assertEqual(result.decisions[("fact", "IN1")], "applicable_unresolved")

    def test_legacy_dates_outside_frozen_interval_remain_failed(self):
        for period in ("2014 12-31", "2022 01-01"):
            with self.subTest(period=period):
                result = self.qualify((self.fact(period),))
                self.assertFalse(result.evidence)
                self.assertEqual(result.decisions[("fact", "IN1")], "applicable_failed")

    def test_extraction_preserves_original_spelling_and_grounding_after_normalization(self):
        from unittest.mock import Mock
        from application.evidence.evidence_extraction_service import EvidenceExtractionService
        from application.ports.evidence_ports import EvidenceCandidate
        from tests.helpers.citation_fixtures import sources_for
        for raw in self.periods:
            with self.subTest(period=raw):
                original = self.fact(raw)
                sources = sources_for((original,))
                repo = Mock()
                repo.get_by_deduplication_key.return_value = None
                service = EvidenceExtractionService(
                    evidence_extractor=Mock(), evidence_repository=repo,
                    source_repository=sources,
                )
                candidate = EvidenceCandidate(
                    statement=original.statement, source_excerpt=original.source_excerpt,
                    evidence_type="direct_excerpt", information_need_refs=("IN1",),
                    research_question_refs=("RQ1",), metadata={"observation_period": raw},
                )
                source = sources.get_by_id(original.source_id)
                service._persist_candidate(
                    candidate=candidate, source=source, project_id=original.project_id,
                    workflow_run_id=original.workflow_run_id, research_design_id=self.design.id,
                )
                persisted = repo.create.call_args.args[0]
                self.assertEqual(persisted.metadata["observation_period"], raw.replace(" ", "-"))
                self.assertEqual(persisted.metadata["observation_period_source"], raw)
                self.assertEqual(persisted.source_excerpt, original.source_excerpt)
                self.assertTrue(citation_is_valid(persisted, source))
                result = qualify_evidence_with_temporal_decisions(
                    design=self.design, evidence=(persisted,), brief=self.brief,
                    source_repository=sources,
                )
                self.assertEqual(result.decisions[(persisted.id, "IN1")], "applicable_satisfied")
                self.assertEqual(len(result.evidence), 1)


class CitationIntegrityTests(unittest.TestCase):
    def test_observation_period_normalizes_grounded_legacy_date_shapes(self):
        self.assertEqual(normalize_observation_period("2016 12-01"), "2016-12-01")
        self.assertEqual(
            normalize_observation_period("1 липня 2025 року до 30 червня 2026 року"),
            "1 липня 2025 to 30 червня 2026",
        )

    def test_ambiguous_observation_period_remains_unknown(self):
        item = SimpleNamespace(
            metadata={"observation_period": "1 липня зазначеного року"},
            statement="Population was recorded on 1 липня зазначеного року.",
            source_excerpt="Population was recorded on 1 липня зазначеного року.",
        )
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "unknown")

    def test_normalized_observation_period_respects_research_window(self):
        item = SimpleNamespace(
            metadata={"observation_period": "2016-12-01", "observation_period_source": "2016 12-01"},
            statement="Population in 2016 12-01.",
            source_excerpt="Population in 2016 12-01.",
        )
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "eligible")
        item.metadata["observation_period"] = "2022"
        item.metadata["observation_period_source"] = "2022"
        item.statement = item.source_excerpt = "Population in 2022."
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "out_of_period")

    def test_publication_only_normalized_date_is_not_observation(self):
        item = SimpleNamespace(
            metadata={"observation_period": "2016-12-01", "observation_period_source": "2016 12-01"},
            statement="The data were published on 2016 12-01.",
            source_excerpt="The data were published on 2016 12-01.",
        )
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "unknown")

    def test_ukrainian_date_range_is_parsed_and_out_of_period(self):
        raw = "1 липня 2025 року до 30 червня 2026 року"
        self.assertIsNotNone(observation_interval(raw))
        item = SimpleNamespace(
            metadata={"observation_period": normalize_observation_period(raw), "observation_period_source": raw},
            statement=raw,
            source_excerpt=raw,
        )
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "out_of_period")

    def test_inconsistent_period_source_and_normalized_value_is_unknown(self):
        item = SimpleNamespace(
            metadata={"observation_period": "2017-12-01", "observation_period_source": "2016 12-01"},
            statement="Population in 2016 12-01.",
            source_excerpt="Population in 2016 12-01.",
        )
        self.assertEqual(observation_eligibility(item, date(2021, 12, 31), start=date(2015, 1, 1)), "unknown")

    def test_valid_span(self):
        self.assertTrue(citation_is_valid(*pair()))

    def test_nested_html_reference_is_normalized_once_for_span_and_hash(self):
        item, source = pair("Literal &amp;lt; text", "Literal &amp;lt; text")
        self.assertTrue(citation_is_valid(item, source))
        self.assertEqual(item.source_locator["excerpt_hash"],
                         sha256("Literal &lt; text".encode()).hexdigest())

    def test_citation_rejection_is_not_labelled_as_temporal_rejection(self):
        from application import research_funnel_telemetry as funnel
        context = SimpleNamespace(execution_metadata={}, shared_state={},
                                  workflow_run=SimpleNamespace(id="fake-method"))
        item, _ = pair()
        @funnel.observed("fake_method")
        def qualify(_self, context):
            return qualifying_evidence(design=ResearchDesign("fake", research_questions=()),
                                       evidence=[item], brief=None)
        self.assertEqual(qualify(None, context), ())
        event = context.shared_state[funnel.KEY]["events"][0]
        self.assertEqual(event["reason"], "invalid_citation")
        self.assertEqual(event["policy"], "canonical_citation_filter")

    def test_invalid_bounds_and_types_fail_closed(self):
        for start, end in [(-1, 8), (0, 999), (4, 3), (3, 3), (True, 10), (0.0, 10), (None, 10)]:
            with self.subTest(start=start, end=end):
                item, source = pair()
                item.source_locator.update(normalized_start=start, normalized_end=end)
                self.assertFalse(citation_is_valid(item, source))

    def test_wrong_source_and_project(self):
        for key in ("id", "project_id"):
            item, source = pair()
            setattr(source, key, "foreign")
            self.assertFalse(citation_is_valid(item, source))

    def test_wrong_checksum_hash_or_span(self):
        for mode in ("source_checksum", "content_drift", "excerpt_hash", "span"):
            with self.subTest(mode=mode):
                item, source = pair()
                if mode == "source_checksum":
                    item.source_content_checksum = "wrong"
                elif mode == "content_drift":
                    source.content_text += "changed"
                elif mode == "excerpt_hash":
                    item.source_locator["excerpt_hash"] = "wrong"
                else:
                    item.source_locator["normalized_start"] -= 1
                self.assertFalse(citation_is_valid(item, source))

    def test_unicode_newline_html_punctuation_and_boundaries(self):
        for text, excerpt in [
            ("  Початок\r\n\tCafé &amp; чай — 42! 🧪\nКінець  ", "Café & чай — 42! 🧪"),
            ("Cafe\u0301\r\nтекст", "Café текст"),
            ("Початок. end", "Початок."), ("start Кінець!", "Кінець!"),
        ]:
            with self.subTest(text=text):
                item, source = pair(text, excerpt)
                self.assertTrue(citation_is_valid(item, source))
                loc = item.source_locator
                self.assertEqual(normalize_source_text(text)[loc["normalized_start"]:loc["normalized_end"]],
                                 normalize_source_text(excerpt))

    def test_repeated_text_prefers_explicit_chunk_deterministically(self):
        item, source = pair("same. gap. same. end", "same.")
        item.source_locator = verify_grounding(source_text=source.content_text,
            excerpt=item.source_excerpt, chunk_normalized_start=11, chunk_normalized_end=16).to_dict()
        self.assertEqual(item.source_locator["normalized_start"], 11)
        self.assertTrue(citation_is_valid(item, source))

    def test_three_ark03_local_offset_shapes_never_qualify(self):
        # Synthetic content, same local/global offsets and lengths; no history edits.
        for local, end, global_start in [(2251, 2421, 9752), (2986, 3286, 10487), (2422, 2910, 9923)]:
            with self.subTest(local=local):
                excerpt = "C" * (end - local)
                item, source = pair("P" * global_start + excerpt + "Z", excerpt)
                repository = SimpleNamespace(get_by_id=lambda _: source)
                design = ResearchDesign("design", research_questions=())
                self.assertEqual(qualifying_evidence(design=design, evidence=[item], brief=None,
                    source_repository=repository), (item,))
                item.source_locator.update(normalized_start=local, normalized_end=end)
                before = deepcopy(item)
                self.assertEqual(qualifying_evidence(design=design, evidence=[item], brief=None,
                    source_repository=repository), ())
                self.assertEqual(vars(item), vars(before))

    def test_generic_method_cannot_qualify_without_source(self):
        item, _ = pair()
        self.assertEqual(qualifying_evidence(design=ResearchDesign("fake-method", research_questions=()), evidence=[item], brief=None), ())

    def test_real_desk_continuation_persists_full_source_offsets(self):
        config, context, sources, evidence, llm, adapter, _, _ = fixture()
        from tests.application.test_ark02_desk import Retriever, Search
        import json
        class SharedSearch(Search):
            def search(self, query):
                return [replace(c, url=f"https://example.test/shared/{i}")
                        for i, c in enumerate(super().search(query))]
        adapter.primitives.acquisition._search_provider.delegate = SharedSearch()
        class LongRetriever(Retriever):
            def retrieve(self, candidate):
                return replace(super().retrieve(candidate),
                    content_text=("Irrigation meter definitions. " + candidate.url + " ") * 1000)
        adapter.primitives.acquisition._source_retriever.delegate = LongRetriever()
        def generate(prompt, *, options=None):
            llm.calls += 1
            refs = [n.id for n in adapter.design.information_needs if n.id in prompt.user]
            items = [] if llm.calls <= 6 else [{"information_need_id": refs[0],
                "statement": "Irrigation meter definitions.", "source_excerpt": "Irrigation meter definitions."}]
            from domain.ai.llm_response import LLMResponse
            return LLMResponse(content=json.dumps({"items": items}), finish_reason="stop")
        llm.generate = generate
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
        rows = evidence.list_for_project(context.project.id)
        self.assertTrue(rows)
        self.assertTrue(any(e.metadata["chunk_normalized_start"] > 0 for e in rows))
        for item in rows:
            self.assertTrue(citation_is_valid(item, sources.get_by_id(item.source_id)))
        self.assertLessEqual(result.used["extractions"], 8)
        bad = rows[0]
        bad.source_locator["normalized_start"] = -1
        self.assertNotIn(bad.id, {e.id for e in adapter.qualified()})

    def test_real_desk_phase_labels_match_ledger(self):
        config, context, _, _, _, adapter, _, _ = fixture()
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
        events = context.shared_state["research_funnel_v1"]["events"]
        extractions = [e for e in events if e["kind"] == "extraction_start"]
        self.assertEqual([e["stage"] for e in extractions], ["initial_extraction"] * 6 + ["continuation_extraction"] * 2)
        self.assertTrue(all(e["stage"] == "initial_acquisition" for e in events if e["kind"] == "acquisition"))
        self.assertTrue(all(e["candidate_ids"] for e in events if e["kind"] == "acquisition"))
        self.assertFalse(any(e.get("reason") == "acquisition_budget_unavailable" for e in events if e["kind"] == "candidate_decision"))
        self.assertEqual(result.used["initial"], 6)
        self.assertEqual(result.used["continuation"], 2)
