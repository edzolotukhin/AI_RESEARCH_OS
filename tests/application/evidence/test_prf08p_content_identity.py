"""Offline content identity and bounded PRF-08O-pattern regressions."""
import unittest
import time
from dataclasses import replace

from application.evidence.content_identity_queue import distinct_content_queue
from application.evidence.evidence_extraction_scheduler import build_need_fair_extraction_queue
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.sources.content_identity import acquired_content_identity
from application.sources.url_canonicalizer import canonicalize_url
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.project import Project
from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.evidence.test_evidence_extraction_service import _design, _source, _template
from tests.application.sources.test_prf08g_coverage import _service, _acquire, _OfflineRetriever, _pending, _design as acquisition_design
from application.sources.source_acquisition_service import _CandidateGroup


def source(sid="a", text="Acquired market report body text."):
    return replace(_source(run_id="run-1", content=text, checksum="raw-" + sid),
                   id=sid, url="https://example.org/" + sid,
                   canonical_url="https://example.org/" + sid)


def queue(sources):
    return build_need_fair_extraction_queue(sources, design=_design(),
        workflow_run_id="run-1", research_design_id="design-1",
        chunk_chars=8000, overlap_chars=500)


class ContentIdentityTests(unittest.TestCase):
    def test_whitespace_unicode_aliases_match_not_url_or_claimed_hash(self):
        self.assertEqual(acquired_content_identity(source("a", "Café  report\n2026")),
                         acquired_content_identity(source("b", "Cafe\u0301 report 2026")))

    def test_distinct_body_with_shared_boilerplate_remains_distinct(self):
        self.assertNotEqual(acquired_content_identity(source("a", "Menu Home. Value 1. Footer")),
                            acquired_content_identity(source("b", "Menu Home. Value 2. Footer")))

    def test_partial_failed_empty_content_not_claimed_identical(self):
        for item in (replace(source(), retrieval_status=RetrievalStatus.TRUNCATED),
                     replace(source(), metadata={"truncated": True}),
                     replace(source(), retrieval_status=RetrievalStatus.FAILED), source(text=" ")):
            self.assertEqual(acquired_content_identity(item), "")

    def test_tracking_variants_canonicalize(self):
        self.assertEqual(canonicalize_url("https://example.org/a?utm_source=x"),
                         canonicalize_url("https://example.org/a"))

    def test_html_representation_matches_grounding_contract(self):
        self.assertEqual(acquired_content_identity(source("a", "A &amp; B")),
                         acquired_content_identity(source("b", "A & B")))

    def test_queue_collapses_alias_preserves_audit_without_mutating_sources(self):
        originals = [source("a"), source("b")]
        result = distinct_content_queue(queue(originals))
        self.assertEqual(len(result), 1)
        self.assertEqual({x["source_id"] for x in result[0].source.metadata["content_aliases"]}, {"a", "b"})
        self.assertNotIn("content_aliases", originals[0].metadata)

    def test_distinct_documents_both_keep_opportunity(self):
        self.assertEqual(len(distinct_content_queue(queue([source(), source("b", "Other report")]))), 2)

    def test_alias_depth_is_not_a_second_document_opportunity(self):
        original = source("a", "Paragraph " * 1600)
        single = queue([original])
        collapsed = distinct_content_queue(queue([original, replace(original, id="b")]))
        self.assertEqual(len(collapsed), len(single))
        self.assertGreater(len(single), 1)

    def test_content_identity_is_full_document_not_chunk(self):
        service, context, repo, _ = self.setup_service()
        service._source_repository.create(source("c", "Acquired market report body text. " * 400))
        service.extract_for_context(context)
        for row in repo.list_for_project("project-1", workflow_run_id="run-1"):
            original = service._source_repository.get_by_id(row.source_id)
            self.assertEqual(row.metadata["acquired_content_identity"], acquired_content_identity(original))

    def test_acquisition_duplicate_is_audited_and_not_refunded(self):
        retriever = _OfflineRetriever()
        result = _acquire(_service(retriever, cap=2), [
            ("IN1", "https://example.org/a"), ("IN2", "https://example.org/b"),
            ("IN3", "https://example.org/c")])
        self.assertEqual(result[4], 2)
        self.assertEqual(len(result[0]), 2)  # provenance retained
        self.assertTrue(any(x.get("reason") == "acquired_duplicate_content" for x in result[12]))
        self.assertEqual(len(retriever.fetched), 2)

    def test_known_duplicate_yields_to_distinct_for_uncovered_need_under_same_cap(self):
        class DistinctRetriever(_OfflineRetriever):
            def retrieve(self, candidate):
                return replace(super().retrieve(candidate), content_text="Distinct alternative report")
        retriever = DistinctRetriever()
        service = _service(retriever, cap=2)
        # First document and its known mirror; multiple needs still uncovered.
        for sid in ("a", "mirror"):
            service._source_repository.create(replace(source(sid, "Synthetic text"), project_id="offline-project"))
        result = _acquire(service, [("IN1", "https://example.org/a"),
            ("IN2", "https://example.org/mirror"), ("IN3", "https://example.org/alternative")])
        self.assertEqual(retriever.fetched, ["https://example.org/alternative"])
        self.assertEqual(result[4], 1)
        self.assertEqual(len(result[0]), 2)

    def test_known_exhausted_alias_cannot_displace_alternative_single_slot(self):
        retriever = _OfflineRetriever()
        service = _service(retriever, cap=1)
        mirror = replace(source("mirror"), project_id="offline-project")
        service._source_repository.create(mirror)
        groups = [_CandidateGroup(canonical_url=url, items=[_pending("IN1", url)])
                  for url in (mirror.url, "https://example.org/alternative")]
        result = service._acquire_candidates(project_id="offline-project", workflow_run_id="offline-run",
            research_design_id="design-offline", design=acquisition_design(), groups=groups,
            started_at=time.monotonic(), max_source_groups=1,
            excluded_content={(acquired_content_identity(mirror), "IN1")})
        self.assertEqual(retriever.fetched, ["https://example.org/alternative"])
        self.assertEqual(result[4], 1)
        self.assertTrue(any(d.get("reason") == "known_exhausted_content" for d in result[12]))

    def test_dedup_keeps_authoritative_cross_need_context_not_other_run(self):
        from tests.application.evidence.test_fair_evidence_extraction_integration import _design as fair_design, _source as fair_source
        a = fair_source("a", need_id="IN1", rq_id="rq-1", content="Same report")
        b = fair_source("b", need_id="IN2", rq_id="rq-2", content="Same report")
        b.metadata["discovery_records"].append({"workflow_run_id": "foreign-run",
            "research_design_id": "design-1", "information_need_id": "IN3", "research_question_id": "rq-3"})
        result = distinct_content_queue(build_need_fair_extraction_queue([a, b], design=fair_design(),
            workflow_run_id="run-fair", research_design_id="design-1", chunk_chars=8000, overlap_chars=500))
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0].run_context.information_need_ids), {"IN1", "IN2"})

    def test_actual_extractor_called_once_and_no_second_independent_evidence(self):
        service, context, repo, extractor = self.setup_service()
        result = service.extract_for_context(context)
        self.assertEqual(len(extractor.calls), 1)
        self.assertEqual(result.evidence_extracted, 1)
        stored = repo.list_for_project("project-1", workflow_run_id="run-1")
        self.assertEqual(len({e.source_id for e in stored}), 1)
        self.assertNotIn("data_lineage", stored[0].metadata)
        from application.research_quality.deterministic_sufficiency_evaluator import _independent_lineages
        self.assertEqual(len(_independent_lineages(stored)[0]), 1)
        self.assertTrue(_independent_lineages(stored)[1])  # unknown remains provisional

    def test_prior_empty_alias_skipped_but_distinct_alternative_extracted(self):
        service, context, _, extractor = self.setup_service()
        service._source_repository.create(source("c", "Acquired distinct report body text."))
        context.shared_state["evidence_extraction"] = {"diagnostics": {"work_items": [{
            "source_id": "a", "information_need_ids": ["in-1"], "extractor_status": "no_candidates",
            "outer_chunk_normalized_start": 0, "outer_chunk_normalized_end": len(source().content_text),
        }]}}
        service.extract_for_source_ids(context, source_ids=("b", "c"), target_information_need_id="in-1", allow_empty=True)
        self.assertEqual(extractor.calls, ["c"])

    def test_technical_failure_does_not_exhaust_alias(self):
        service, context, _, extractor = self.setup_service()
        context.shared_state["evidence_extraction"] = {"diagnostics": {"work_items": [{
            "source_id": "a", "information_need_ids": ["in-1"], "extractor_status": "no_candidates",
            "outer_chunk_normalized_start": 0, "outer_chunk_normalized_end": len(source().content_text),
            "inner_chunks": [{"response_shape": {"response_classification": "invalid_json"}}],
        }]}}
        service.extract_for_source_ids(context, source_ids=("b",), target_information_need_id="in-1")
        self.assertEqual(extractor.calls, ["b"])

    def setup_service(self):
        class CountingExtractor(DeterministicEvidenceExtractor):
            def __init__(self):
                self.calls = []

            def extract(self, **kwargs):
                self.calls.append(kwargs["source"].id)
                return super().extract(**kwargs)
        template = _template(_design())
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(project=Project(id="project-1", name="Synthetic"),
                                  workflow_template=template, workflow_run=run)
        context.current_task = run.tasks[0]
        sources, evidence = InMemorySourceRepository(), InMemoryEvidenceRepository()
        sources.create(source("a"))
        sources.create(source("b"))
        extractor = CountingExtractor()
        return EvidenceExtractionService(evidence_extractor=extractor,
            source_repository=sources, evidence_repository=evidence), context, evidence, extractor
