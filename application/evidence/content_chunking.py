from __future__ import annotations

from dataclasses import dataclass

from application.evidence.grounding import normalize_source_text

DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS = 8000
DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS = 500


@dataclass(frozen=True)
class SourceContentChunk:
    text: str
    original_normalized_start: int
    original_normalized_end: int


def split_normalized_source_content(
    content_text: str,
    *,
    chunk_chars: int,
    overlap_chars: int,
) -> list[SourceContentChunk]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be non-negative")
    if overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars must be smaller than chunk_chars")

    normalized = normalize_source_text(content_text)
    if not normalized:
        return []

    chunks: list[SourceContentChunk] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + chunk_chars, length)
        chunks.append(
            SourceContentChunk(
                text=normalized[start:end],
                original_normalized_start=start,
                original_normalized_end=end,
            ),
        )
        if end >= length:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
