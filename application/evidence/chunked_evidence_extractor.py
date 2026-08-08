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
from application.evidence.evidence_extraction_diagnostics import (
    InnerChunkObservation,
    record_inner_chunk_observation,
)
from application.execution.budget_utils import is_evidence_graceful_budget_stop
from application.execution.exceptions import BudgetExhaustedError
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
        for inner_index, chunk in enumerate(chunks):
            chunk_source = replace(source, content_text=chunk.text)
            inner_status = "success"
            inner_exception_class: str | None = None
            inner_exception_message: str | None = None
            inner_candidate_count = 0
            try:
                chunk_candidates = self._inner.extract(
                    source=chunk_source,
                    design=design,
                    run_context=run_context,
                )
            except BudgetExhaustedError as exc:
                if is_evidence_graceful_budget_stop(exc):
                    inner_status = "budget_stop"
                    record_inner_chunk_observation(
                        InnerChunkObservation(
                            inner_chunk_index=inner_index,
                            inner_chunk_normalized_start=chunk.original_normalized_start,
                            inner_chunk_normalized_end=chunk.original_normalized_end,
                            inner_chunk_length=len(chunk.text),
                            extractor_status=inner_status,
                            exception_class=type(exc).__name__,
                            exception_message=str(exc),
                        ),
                    )
                    return candidates
                raise
            except Exception as exc:
                inner_status = "exception"
                inner_exception_class = type(exc).__name__
                inner_exception_message = str(exc)
                record_inner_chunk_observation(
                    InnerChunkObservation(
                        inner_chunk_index=inner_index,
                        inner_chunk_normalized_start=chunk.original_normalized_start,
                        inner_chunk_normalized_end=chunk.original_normalized_end,
                        inner_chunk_length=len(chunk.text),
                        extractor_status=inner_status,
                        exception_class=inner_exception_class,
                        exception_message=inner_exception_message,
                    ),
                )
                continue
            inner_candidate_count = len(chunk_candidates)
            record_inner_chunk_observation(
                InnerChunkObservation(
                    inner_chunk_index=inner_index,
                    inner_chunk_normalized_start=chunk.original_normalized_start,
                    inner_chunk_normalized_end=chunk.original_normalized_end,
                    inner_chunk_length=len(chunk.text),
                    extractor_status=inner_status,
                    raw_candidate_count=inner_candidate_count,
                ),
            )
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
