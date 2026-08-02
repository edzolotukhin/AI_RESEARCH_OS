from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.evidence.run_scoped_provenance import resolve_run_scoped_context
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)


def _design(*, design_id: str, rq_id: str, in_id: str, question: str) -> ResearchDesign:
    return ResearchDesign(
        id=design_id,
        research_questions=(
            ResearchQuestion(id=rq_id, question=question, objective_refs=()),
        ),
        information_needs=(
            InformationNeed(
                id=in_id,
                research_question_id=rq_id,
                description=f"Need for {question}",
            ),
        ),
    )


def _shared_source(*, content: str) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    return Source(
        id="source-shared",
        project_id="project-1",
        url="https://example.com/shared",
        canonical_url="https://example.com/shared",
        title="Shared report",
        retrieved_at=now,
        retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=content,
        content_checksum="shared-checksum",
        query_refs=("sq-in-a", "sq-in-b"),
        research_question_refs=("rq-a", "rq-b"),
        information_need_refs=("in-a", "in-b"),
        workflow_run_refs=("run-a", "run-b"),
        research_design_refs=("design-a", "design-b"),
        metadata={
            "discovery_records": [
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-a",
                    "rank": 1,
                    "workflow_run_id": "run-a",
                    "research_design_id": "design-a",
                },
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-b",
                    "rank": 1,
                    "workflow_run_id": "run-b",
                    "research_design_id": "design-b",
                },
            ],
        },
    )


class RunScopedProvenanceTests(unittest.TestCase):
    def test_shared_source_with_same_local_ids_resolves_per_run_design(self) -> None:
        source = Source(
            id="source-shared",
            project_id="project-1",
            url="https://example.com/shared",
            canonical_url="https://example.com/shared",
            title="Shared report",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="Acquired market report body text.",
            content_checksum="shared-checksum",
            query_refs=("sq-in-rq-1",),
            research_question_refs=("rq-1",),
            information_need_refs=("in-rq-1",),
            workflow_run_refs=("run-a", "run-b"),
            research_design_refs=("design-a", "design-b"),
            metadata={
                "discovery_records": [
                    {
                        "provider": "deterministic",
                        "query_id": "sq-in-rq-1",
                        "rank": 1,
                        "workflow_run_id": "run-a",
                        "research_design_id": "design-a",
                        "research_question_id": "rq-1",
                        "information_need_id": "in-rq-1",
                    },
                    {
                        "provider": "deterministic",
                        "query_id": "sq-in-rq-1",
                        "rank": 1,
                        "workflow_run_id": "run-b",
                        "research_design_id": "design-b",
                        "research_question_id": "rq-1",
                        "information_need_id": "in-rq-1",
                    },
                ],
            },
        )
        design_a = _design(
            design_id="design-a",
            rq_id="rq-1",
            in_id="in-rq-1",
            question="Question A",
        )
        design_b = _design(
            design_id="design-b",
            rq_id="rq-1",
            in_id="in-rq-1",
            question="Question B",
        )

        context_a = resolve_run_scoped_context(
            source=source,
            design=design_a,
            workflow_run_id="run-a",
            research_design_id="design-a",
        )
        context_b = resolve_run_scoped_context(
            source=source,
            design=design_b,
            workflow_run_id="run-b",
            research_design_id="design-b",
        )

        self.assertEqual(context_a.information_need_ids, ("in-rq-1",))
        self.assertEqual(context_a.research_question_ids, ("rq-1",))
        self.assertEqual(context_b.information_need_ids, ("in-rq-1",))
        self.assertEqual(context_b.research_question_ids, ("rq-1",))

    def test_shared_source_resolves_run_specific_needs_from_discovery_records(self) -> None:
        source = _shared_source(content="Acquired market report body text.")
        design_a = _design(
            design_id="design-a",
            rq_id="rq-a",
            in_id="in-a",
            question="Question A",
        )
        design_b = _design(
            design_id="design-b",
            rq_id="rq-b",
            in_id="in-b",
            question="Question B",
        )

        context_a = resolve_run_scoped_context(
            source=source,
            design=design_a,
            workflow_run_id="run-a",
            research_design_id="design-a",
        )
        context_b = resolve_run_scoped_context(
            source=source,
            design=design_b,
            workflow_run_id="run-b",
            research_design_id="design-b",
        )

        self.assertEqual(context_a.information_need_ids, ("in-a",))
        self.assertEqual(context_a.research_question_ids, ("rq-a",))
        self.assertEqual(context_b.information_need_ids, ("in-b",))
        self.assertEqual(context_b.research_question_ids, ("rq-b",))

    def test_cross_run_extraction_does_not_leak_semantic_refs(self) -> None:
        source = _shared_source(content="Acquired market report body text.")
        design_a = _design(
            design_id="design-a",
            rq_id="rq-a",
            in_id="in-a",
            question="Question A",
        )
        design_b = _design(
            design_id="design-b",
            rq_id="rq-b",
            in_id="in-b",
            question="Question B",
        )
        repository = InMemoryEvidenceRepository()
        service = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=repository,
            source_repository=_StaticSourceRepository(source),
        )

        run_a_ids, _, _, _ = service._extract_from_source(
            source=source,
            design=design_a,
            project_id="project-1",
            workflow_run_id="run-a",
            research_design_id="design-a",
        )
        run_b_ids, _, _, _ = service._extract_from_source(
            source=source,
            design=design_b,
            project_id="project-1",
            workflow_run_id="run-b",
            research_design_id="design-b",
        )

        evidence_a = repository.get_by_id(run_a_ids[0])
        evidence_b = repository.get_by_id(run_b_ids[0])
        assert evidence_a is not None
        assert evidence_b is not None

        self.assertEqual(evidence_a.workflow_run_id, "run-a")
        self.assertEqual(evidence_a.research_design_id, "design-a")
        self.assertEqual(evidence_a.information_need_refs, ("in-a",))
        self.assertEqual(evidence_a.research_question_refs, ("rq-a",))
        self.assertNotIn("in-b", evidence_a.information_need_refs)
        self.assertNotIn("rq-b", evidence_a.research_question_refs)

        self.assertEqual(evidence_b.workflow_run_id, "run-b")
        self.assertEqual(evidence_b.research_design_id, "design-b")
        self.assertEqual(evidence_b.information_need_refs, ("in-b",))
        self.assertEqual(evidence_b.research_question_refs, ("rq-b",))
        self.assertNotIn("in-a", evidence_b.information_need_refs)
        self.assertNotIn("rq-a", evidence_b.research_question_refs)


class _StaticSourceRepository:
    def __init__(self, source: Source) -> None:
        self._source = source

    def list_for_project(self, project_id: str, *, workflow_run_id: str | None = None):
        if workflow_run_id in self._source.workflow_run_refs:
            return [self._source]
        return []


if __name__ == "__main__":
    unittest.main()
