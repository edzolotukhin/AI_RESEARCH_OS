from __future__ import annotations

from dataclasses import dataclass

from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.content_chunking import (
    SourceContentChunk,
    split_normalized_source_content,
)
from application.evidence.run_scoped_provenance import (
    RunScopedSourceContext,
    resolve_run_scoped_context,
)


@dataclass(frozen=True)
class EvidenceExtractionWorkItem:
    """One bounded extraction opportunity: a single chunk from one source."""

    source: Source
    chunk: SourceContentChunk
    run_context: RunScopedSourceContext


def build_need_fair_extraction_queue(
    sources: list[Source],
    *,
    design: ResearchDesign,
    workflow_run_id: str,
    research_design_id: str,
    chunk_chars: int,
    overlap_chars: int,
) -> list[EvidenceExtractionWorkItem]:
    """
    Build a deterministic round-robin queue across InformationNeeds.

    Each work item represents one chunk-level LLM call opportunity. Needs are
    visited in sorted ID order; within each need, sources are sorted by ID.
    The queue interleaves first chunks across needs before second chunks.
    """
    buckets: dict[str, list[EvidenceExtractionWorkItem]] = {}

    for source in sorted(sources, key=lambda item: item.id):
        run_context = resolve_run_scoped_context(
            source=source,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )
        if not run_context.information_need_ids:
            continue

        primary_need = sorted(run_context.information_need_ids)[0]
        chunks = split_normalized_source_content(
            source.content_text,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        if not chunks:
            continue

        for chunk in chunks:
            buckets.setdefault(primary_need, []).append(
                EvidenceExtractionWorkItem(
                    source=source,
                    chunk=chunk,
                    run_context=run_context,
                ),
            )

    if not buckets:
        return []

    need_ids = sorted(buckets.keys())
    indices = {need_id: 0 for need_id in need_ids}
    queue: list[EvidenceExtractionWorkItem] = []

    while True:
        progressed = False
        for need_id in need_ids:
            items = buckets[need_id]
            index = indices[need_id]
            if index < len(items):
                queue.append(items[index])
                indices[need_id] = index + 1
                progressed = True
        if not progressed:
            break

    return queue
