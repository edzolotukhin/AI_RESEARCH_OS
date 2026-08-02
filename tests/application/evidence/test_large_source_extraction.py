from __future__ import annotations

import unittest
from datetime import datetime, timezone

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.evidence.chunked_evidence_extractor import ChunkedEvidenceExtractor
from application.evidence.content_chunking import split_normalized_source_content
from application.evidence.grounding import normalize_source_text
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)


class _TrackingExtractor(EvidenceExtractor):
    method_name = "tracking"

    def __init__(self, *, marker: str) -> None:
        self.marker = marker
        self.max_input_len = 0
        self.chunk_count = 0

    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        self.max_input_len = max(self.max_input_len, len(source.content_text))
        self.chunk_count += 1
        if self.marker not in source.content_text:
            return []
        return [
            EvidenceCandidate(
                statement=f"Found marker in chunk {self.chunk_count}",
                source_excerpt=self.marker,
                evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                research_question_refs=run_context.research_question_ids,
                information_need_refs=run_context.information_need_ids,
            ),
        ]


class LargeSourceExtractionTests(unittest.TestCase):
    def test_large_source_is_chunked_and_later_chunk_evidence_is_grounded(self) -> None:
        chunk_chars = 200
        overlap_chars = 40
        prefix = "alpha " * 120
        marker = "TARGET-EXCERPT"
        suffix = " omega " * 120
        content = prefix + marker + suffix
        normalized = normalize_source_text(content)
        chunks = split_normalized_source_content(
            content,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        self.assertGreater(len(chunks), 1)

        tracking = _TrackingExtractor(marker=marker)
        extractor = ChunkedEvidenceExtractor(
            tracking,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )

        design = ResearchDesign(
            id="design-large",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need one",
                ),
            ),
        )
        run_context = RunScopedSourceContext(
            workflow_run_id="run-large",
            research_design_id="design-large",
            information_need_ids=("in-1",),
            research_question_ids=("rq-1",),
            query_ids=("sq-in-1",),
        )
        now = datetime.now(timezone.utc).isoformat()
        source = Source(
            id="source-large",
            project_id="project-1",
            url="https://example.com/large",
            canonical_url="https://example.com/large",
            title="Large",
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=content,
            content_checksum="large-checksum",
            metadata={
                "discovery_records": [
                    {
                        "provider": "test",
                        "query_id": "sq-in-1",
                        "rank": 1,
                        "workflow_run_id": "run-large",
                        "research_design_id": "design-large",
                    },
                ],
            },
        )

        candidates = extractor.extract(
            source=source,
            design=design,
            run_context=run_context,
        )
        self.assertGreater(tracking.chunk_count, 1)
        self.assertLessEqual(tracking.max_input_len, chunk_chars)
        self.assertGreaterEqual(len(candidates), 1)

        repository = InMemoryEvidenceRepository()
        service = EvidenceExtractionService(
            evidence_extractor=extractor,
            evidence_repository=repository,
            source_repository=_StaticSourceRepository(source),
        )
        ids, extracted, _, had_none = service._extract_from_source(
            source=source,
            design=design,
            project_id="project-1",
            workflow_run_id="run-large",
            research_design_id="design-large",
        )
        self.assertFalse(had_none)
        self.assertEqual(extracted, 1)
        evidence = repository.get_by_id(ids[0])
        assert evidence is not None
        self.assertEqual(evidence.source_content_checksum, "large-checksum")
        start = evidence.source_locator["normalized_start"]
        end = evidence.source_locator["normalized_end"]
        self.assertEqual(normalized[start:end], normalize_source_text(marker))


class OverlapDedupTests(unittest.TestCase):
    def test_overlap_extracts_single_durable_evidence_row(self) -> None:
        chunk_chars = 80
        overlap_chars = 30
        marker = "SHARED-OVERLAP-EXCERPT"
        content = f"{'prefix ' * 20}{marker}{' suffix' * 20}"
        design = ResearchDesign(
            id="design-overlap",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q1", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Need one",
                ),
            ),
        )
        now = datetime.now(timezone.utc).isoformat()
        source = Source(
            id="source-overlap",
            project_id="project-1",
            url="https://example.com/overlap",
            canonical_url="https://example.com/overlap",
            title="Overlap",
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text=content,
            content_checksum="overlap-checksum",
            workflow_run_refs=("run-overlap",),
            research_design_refs=("design-overlap",),
            metadata={
                "discovery_records": [
                    {
                        "provider": "test",
                        "query_id": "sq-in-1",
                        "rank": 1,
                        "workflow_run_id": "run-overlap",
                        "research_design_id": "design-overlap",
                    },
                ],
            },
        )
        tracking = _TrackingExtractor(marker=marker)
        extractor = ChunkedEvidenceExtractor(
            tracking,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        repository = InMemoryEvidenceRepository()
        service = EvidenceExtractionService(
            evidence_extractor=extractor,
            evidence_repository=repository,
            source_repository=_StaticSourceRepository(source),
        )
        ids, extracted, _, _ = service._extract_from_source(
            source=source,
            design=design,
            project_id="project-1",
            workflow_run_id="run-overlap",
            research_design_id="design-overlap",
        )
        self.assertEqual(extracted, 1)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(
            len(repository.list_for_project("project-1", workflow_run_id="run-overlap")),
            1,
        )


class _StaticSourceRepository:
    def __init__(self, source: Source) -> None:
        self._source = source

    def list_for_project(self, project_id: str, *, workflow_run_id: str | None = None):
        return [self._source]


if __name__ == "__main__":
    unittest.main()
