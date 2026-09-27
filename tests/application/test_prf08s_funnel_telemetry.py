"""Deterministic provider-free funnel and observational-invariant tests."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from uuid import UUID

from application import research_funnel_telemetry as funnel
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.ports.evidence_ports import EvidenceCandidate
from application.ports.source_ports import SearchProvider, SourceRetriever
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed
from domain.sources.source_candidate import SourceCandidate
from domain.sources.source import Source
from domain.sources.retrieval_status import RetrievalStatus
from domain.research_brief import ResearchBrief


class Search(SearchProvider):
    def search(self, query):
        return [SourceCandidate(provider="offline", url=f"https://example.org/{name}",
            title="Synthetic report", snippet="RAW_PROVIDER_PRIVATE", query_id=query.id, rank=i)
            for i, name in enumerate(("empty-a", "mirror-a", "empty-b", "useful", "unused"), 1)]


class Retriever(SourceRetriever):
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def retrieve(self, candidate):
        self.calls.append(candidate.url)
        name = candidate.url.rsplit("/", 1)[-1]
        text = "Private page empty A" if name in {"empty-a", "mirror-a"} else "Private page " + name
        failed = self.fail and name == "empty-a"
        return Source(id="", project_id="", url=candidate.url, canonical_url=candidate.url,
            title="Synthetic report", retrieved_at="2026-01-01T00:00:00+00:00",
            retrieval_status=RetrievalStatus.FAILED if failed else RetrievalStatus.ACQUIRED,
            content_text="" if failed else text,
            metadata={"failure_category": "timeout"} if failed else {})


class Extractor:
    method_name = "offline"

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def extract(self, *, source, design, run_context):
        self.calls.append((source.id, run_context.information_need_ids, run_context.target_information_need_id))
        if self.fail:
            raise RuntimeError("RAW_LLM_PRIVATE")
        if "useful" not in source.content_text:
            return []
        return [EvidenceCandidate(statement="Synthetic useful finding", source_excerpt="Private page useful",
            evidence_type="direct_excerpt", information_need_refs=("in-2",), research_question_refs=("rq-1",))]


def run_fixture(enabled=True, *, fail_fetch=False, fail_extract=False, target=None):
    from tests.application.evidence.test_prf08p_content_identity import ContentIdentityTests
    _, context, evidence, _ = ContentIdentityTests().setup_service()
    from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
    sources = InMemorySourceRepository()
    design = ResearchDesign(id="design-1", research_questions=(ResearchQuestion(id="rq-1", question="Synthetic report"),),
        information_needs=tuple(InformationNeed(id=f"in-{i}", research_question_id="rq-1", description="Synthetic report") for i in (1, 2, 3)))
    context.workflow_template.research_design_snapshot = design
    context.execution_metadata["research_funnel_enabled"] = enabled
    retriever, extractor = Retriever(fail_fetch), Extractor(fail_extract)
    acquisition = SourceAcquisitionService(search_provider=Search(), source_retriever=retriever,
        source_repository=sources, budget=SourceAcquisitionBudget(max_sources_per_run=4, min_successful_sources=3))
    with patch("application.sources.source_acquisition_service.uuid4", side_effect=[UUID(int=i) for i in range(1, 20)]):
        acquired = acquisition.acquire_for_context(context)
    service = EvidenceExtractionService(evidence_extractor=extractor, source_repository=sources, evidence_repository=evidence)
    with patch("application.evidence.evidence_extraction_service.uuid4", side_effect=[UUID(int=i) for i in range(100, 120)]):
        if target:
            extracted = service.extract_for_source_ids(context, acquired.source_ids, allow_empty=True, target_information_need_id=target)
        else:
            try:
                extracted = service.extract_for_context(context)
            except Exception:
                if not fail_extract:
                    raise
                extracted = None
    readiness = ResearchReadinessService(evaluator=DeterministicResearchSufficiencyEvaluator(),
                                        evidence_repository=evidence, source_repository=sources)
    result = readiness.evaluate_for_context(context)
    return context, acquired, extracted, result, retriever, extractor, evidence, readiness


class FunnelTests(unittest.TestCase):
    def events(self, fixture, kind):
        journal = fixture[0].shared_state[funnel.KEY]
        self.assertEqual(journal["observer_errors"], 0)
        return [e for e in journal["events"] if e["kind"] == kind]

    def test_search_multiple_candidates_join_exact_queries(self):
        f = run_fixture()
        searches = self.events(f, "search")
        candidates = self.events(f, "candidate")
        self.assertEqual(len(searches), 3)
        self.assertEqual(len(candidates), 15)
        self.assertTrue(all(s["query_exact"] for s in searches))
        self.assertEqual({c["search_id"] for c in candidates}, {s["event_id"] for s in searches})
        self.assertEqual(len({c["candidate_id"] for c in candidates}), 15)

    def test_selected_and_unused_each_have_decision(self):
        f = run_fixture()
        candidates = self.events(f, "candidate")
        decisions = self.events(f, "candidate_decision")
        self.assertEqual({c["candidate_id"] for c in candidates}, {d["candidate_id"] for d in decisions})
        self.assertTrue(any(d["selected"] for d in decisions))
        unused = {c["candidate_id"] for c in candidates if c["url"].endswith("unused")}
        self.assertTrue(unused)
        self.assertTrue(all(not d["selected"] and d["reason"] != "pending" for d in decisions if d["candidate_id"] in unused))

    def test_acquisition_success_failure_links_to_candidate(self):
        f = run_fixture(fail_fetch=True)
        events = self.events(f, "acquisition")
        self.assertTrue(any(e["status"] == "failed" and e["failure_category"] == "timeout" for e in events))
        self.assertTrue(any(e["status"] == "acquired" for e in events))
        decisions = self.events(f, "candidate_decision")
        self.assertTrue(all(any(d["source_id"] == e["source_id"] for d in decisions) for e in events))

    def test_duplicate_content_visible_without_page_body(self):
        f = run_fixture()
        self.assertTrue(self.events(f, "content_dedup"))
        self.assertTrue(any(e["reason"] == "duplicate_content" for e in self.events(f, "extraction_skipped")))
        self.assertNotIn("Private page", json.dumps(f[0].shared_state[funnel.KEY]))

    def test_valid_empty_not_failure(self):
        self.assertTrue(any(e["status"] == "valid_empty" for e in self.events(run_fixture(), "extraction_result")))
        self.assertTrue(any(e["status"] == "failure" for e in self.events(run_fixture(fail_extract=True), "extraction_result")))

    def test_continuation_cross_in_is_not_target_success(self):
        f = run_fixture(target="in-1")
        results = self.events(f, "extraction_result")
        productive = [e for e in results if e["evidence_count"]]
        self.assertEqual(len(productive), 1)
        self.assertEqual(productive[0]["target_in"], "in-1")
        self.assertEqual(productive[0]["target_evidence_count"], 0)
        self.assertEqual(productive[0]["cross_only_evidence_count"], 1)
        self.assertEqual(productive[0]["stage"], "continuation_extraction")
        produced = self.events(f, "evidence")
        self.assertEqual(produced[0]["supported_ins"], ["in-2"])
        self.assertEqual(produced[0]["extraction_id"], productive[0]["extraction_id"])

    def test_actual_temporal_rejection_visible(self):
        f = run_fixture()
        evidence = f[6].list_for_project("project-1", workflow_run_id="run-1")[0]
        f[6].create(replace(evidence, id="future", deduplication_key="future", source_excerpt="1 July 2027",
            metadata={"observation_period": "1 July 2027"}))
        from tests.helpers.citation_fixtures import sources_for
        sources_for(f[6].list_for_project("project-1"), f[7]._source_repository)
        f[0].workflow_template.research_brief_snapshot = ResearchBrief(title="Synthetic", business_question="Synthetic", timeframe="1 July 2026")
        f[7].evaluate_for_context(f[0])
        rejected = [e for e in self.events(f, "qualification") if e["evidence_id"] == "future"]
        self.assertEqual(rejected[-1]["reason"], "applicable_failed")
        self.assertFalse(rejected[-1]["qualifying"])

    def test_o_pattern_and_on_off_decisions_identical(self):
        on, off = run_fixture(), run_fixture(False)
        self.assertNotIn(funnel.KEY, off[0].shared_state)
        a, b = on[1].to_dict(), off[1].to_dict()
        a.pop("elapsed_seconds"); b.pop("elapsed_seconds")
        self.assertEqual(a, b)
        self.assertEqual(on[4].calls, off[4].calls)
        self.assertEqual(on[5].calls, off[5].calls)
        self.assertEqual(on[3].to_dict(), off[3].to_dict())
        self.assertFalse(on[3].ready_for_analysis)
        results = self.events(on, "extraction_result")
        self.assertGreaterEqual(sum(e["status"] == "valid_empty" for e in results), 2)
        self.assertEqual(sum(e["evidence_count"] for e in results), 1)
        self.assertEqual(sum(e["qualifying"] for e in self.events(on, "qualification")), 1)

    def test_no_raw_responses_or_secrets(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "OPAQUE_TEST_SECRET"}):
            f = run_fixture()
            journal = json.dumps(f[0].shared_state[funnel.KEY])
            for forbidden in ("Private page", "RAW_PROVIDER_PRIVATE", "RAW_LLM_PRIVATE", "OPAQUE_TEST_SECRET", "response_preview", "Authorization"):
                self.assertNotIn(forbidden, journal)
            self.assertNotIn("OPAQUE_TEST_SECRET", funnel.safe_text("OPAQUE_TEST_SECRET"))
            self.assertNotIn("credential", funnel.safe_url("https://u:credential@example.org/a?token=credential"))

    def test_checkpoint_codec_preserves_journal(self):
        from application.runtime.task_result_codec import capture_task_result
        f = run_fixture()
        snapshot = capture_task_result(f[0], f[0].current_task.id)
        self.assertEqual(snapshot["shared_state"][funnel.KEY], f[0].shared_state[funnel.KEY])

    def test_invalid_output_and_retry_ordinals_no_raw_preview(self):
        from application.evidence.evidence_extraction_diagnostics import WorkItemTrace, InnerChunkObservation
        from application.evidence.evidence_extractor_response_shape import ResponseShapeDiagnostics
        f = run_fixture()
        trace = WorkItemTrace(0, "source", "hash", ("in-1",), 0, 0, 10, 10,
            extractor_status="no_candidates", primary_need_id="in-1")
        trace.inner_chunks.append(InnerChunkObservation(0, 0, 10, 10, "success",
            response_shape=ResponseShapeDiagnostics(response_classification="invalid_json",
                structured_attempts=2, response_preview="RAW_LLM_PRIVATE")))
        class Probe:
            @funnel.observed("continuation_extraction")
            def run(self, context):
                funnel.extraction_result("extraction-fixture", trace)
        Probe().run(f[0])
        self.assertEqual(self.events(f, "extraction_result")[-1]["status"], "invalid_output")
        self.assertEqual([e["retry_ordinal"] for e in self.events(f, "extraction_attempt")], [0, 1])
        self.assertNotIn("RAW_LLM_PRIVATE", json.dumps(f[0].shared_state[funnel.KEY]))

    def test_budget_skipped_opportunity_visible(self):
        from application.evidence.evidence_extraction_diagnostics import EvidenceExtractionDiagnostics
        from tests.application.evidence.test_prf08p_content_identity import queue, source
        f = run_fixture()
        class Probe:
            @funnel.observed("continuation_extraction")
            def run(self, context):
                funnel.extraction_unattempted(queue([source()]), EvidenceExtractionDiagnostics(workflow_run_id="run-1", budget_stop=True))
        Probe().run(f[0])
        self.assertEqual(self.events(f, "extraction_skipped")[-1]["reason"], "extraction_budget_unavailable")

    def test_bounded_journal_reports_truncation_without_affecting_result(self):
        with patch.object(funnel, "MAX_EVENTS", 3):
            f = run_fixture()
        self.assertEqual(len(f[0].shared_state[funnel.KEY]["events"]), 3)
        self.assertGreater(f[0].shared_state[funnel.KEY]["dropped_events"], 0)
        self.assertEqual(f[3].to_dict(), run_fixture(False)[3].to_dict())

    def test_secret_query_marked_not_exact_and_malformed_url_safe(self):
        from domain.sources.search_query import SearchQuery
        f = run_fixture()
        class Probe:
            @funnel.observed("initial_search")
            def run(self, context):
                funnel.search_start(SearchQuery(id="q", research_question_id="rq-1", information_need_id="in-1",
                    query_text='report password="private phrase"'))
        Probe().run(f[0])
        last = self.events(f, "search")[-1]
        self.assertFalse(last["query_exact"])
        self.assertNotIn("private phrase", last["query"])
        self.assertEqual(funnel.safe_url("https://[invalid"), "[INVALID_URL]")
