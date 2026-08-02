from __future__ import annotations

from dataclasses import replace

from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.content_chunking import (
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
    split_normalized_source_content,
)
from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor


class ChunkedEvidenceExtractor:
    """Bounded-input wrapper that extracts evidence chunk-by-chunk."""

    method_name = "chunked"

    def __init__(
        self,
        inner: EvidenceExtractor,
        *,
        chunk_chars: int = DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
    ) -> None:
        self._inner = inner
        self._chunk_chars = chunk_chars
        self._overlap_chars = overlap_chars
        self.method_name = getattr(inner, "method_name", "chunked")

    @property
    def chunk_chars(self) -> int:
        return self._chunk_chars

    @property
    def overlap_chars(self) -> int:
        return self._overlap_chars

    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        chunks = split_normalized_source_content(
            source.content_text,
            chunk_chars=self._chunk_chars,
            overlap_chars=self._overlap_chars,
        )
        if not chunks:
            return []

        candidates: list[EvidenceCandidate] = []
        for chunk in chunks:
            chunk_source = replace(source, content_text=chunk.text)
            try:
                chunk_candidates = self._inner.extract(
                    source=chunk_source,
                    design=design,
                    run_context=run_context,
                )
            except Exception:
                continue
            for candidate in chunk_candidates:
                metadata = dict(candidate.metadata or {})
                metadata["chunk_normalized_start"] = chunk.original_normalized_start
                metadata["chunk_normalized_end"] = chunk.original_normalized_end
                candidates.append(
                    EvidenceCandidate(
                        statement=candidate.statement,
                        source_excerpt=candidate.source_excerpt,
                        evidence_type=candidate.evidence_type,
                        research_question_refs=candidate.research_question_refs,
                        information_need_refs=candidate.information_need_refs,
                        confidence=candidate.confidence,
                        direct=candidate.direct,
                        metadata=metadata,
                    ),
                )
        return candidates
