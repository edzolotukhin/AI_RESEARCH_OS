"""Offline citation contract and actual Desk continuation regression."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
import unittest

from application.evidence.citation_integrity import citation_is_valid
from application.evidence.grounding import normalize_source_text, verify_grounding
from application.evidence.temporal_scope import qualifying_evidence
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


class CitationIntegrityTests(unittest.TestCase):
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
