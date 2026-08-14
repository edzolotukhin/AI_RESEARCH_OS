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

PHASE_FIRST_OPPORTUNITY = "first_opportunity"
PHASE_DEPTH = "depth"
EXTRACTION_ORDERING_COVERAGE_BEFORE_DEPTH = "coverage_before_depth_need_fair"
SELECTION_FIRST_OPPORTUNITY = "first_opportunity"
SELECTION_EXPLORATORY_DEPTH = "exploratory_depth"
SELECTION_PRODUCTIVE_DEPTH = "productive_depth"
SELECTION_DEPRIORITIZED_EMPTY_DEPTH = "deprioritized_repeated_empty_depth"


@dataclass(frozen=True)
class EvidenceExtractionWorkItem:
    """One bounded extraction opportunity: a single chunk from one source."""

    source: Source
    chunk: SourceContentChunk
    run_context: RunScopedSourceContext
    phase: str = PHASE_DEPTH
    source_first_attempt: bool = False
    chunk_index: int = 0
    primary_need_id: str = ""


@dataclass
class SourceOutcomeState:
    """Run-local observed extraction outcomes used only for depth allocation."""

    source_id: str
    calls_attempted: int = 0
    productive_calls: int = 0
    valid_empty_calls: int = 0
    evidence_yielded: int = 0
    depth_calls: int = 0
    consecutive_empty_depth: int = 0
    first_opportunity_completed: bool = False
    last_outcome: str = "unobserved"

    @property
    def repeated_zero_yield(self) -> bool:
        return self.productive_calls == 0 and self.valid_empty_calls >= 2

    def to_dict(self) -> dict[str, int | str | bool]:
        return {
            "source_id": self.source_id,
            "calls_attempted": self.calls_attempted,
            "productive_calls": self.productive_calls,
            "valid_empty_calls": self.valid_empty_calls,
            "evidence_yielded": self.evidence_yielded,
            "depth_calls": self.depth_calls,
            "consecutive_empty_depth": self.consecutive_empty_depth,
            "first_opportunity_completed": self.first_opportunity_completed,
            "last_outcome": self.last_outcome,
            "repeated_zero_yield": self.repeated_zero_yield,
        }


def record_source_outcome(
    state: SourceOutcomeState,
    *,
    phase: str,
    persisted_evidence: int,
    valid_empty: bool,
) -> None:
    """Record an executed outcome without predicting any unexecuted chunk."""
    state.calls_attempted += 1
    if phase == PHASE_FIRST_OPPORTUNITY:
        state.first_opportunity_completed = True
    else:
        state.depth_calls += 1
    if persisted_evidence > 0:
        state.productive_calls += 1
        state.evidence_yielded += persisted_evidence
        state.consecutive_empty_depth = 0
        state.last_outcome = "productive"
    elif valid_empty:
        state.valid_empty_calls += 1
        if phase == PHASE_DEPTH:
            state.consecutive_empty_depth += 1
        state.last_outcome = "valid_empty"
    else:
        state.last_outcome = "non_productive_other"


def adaptive_depth_selection_key(
    work_item: EvidenceExtractionWorkItem,
    *,
    state: SourceOutcomeState,
    evidence_counts_by_need: dict[str, int],
) -> tuple[int, int, int, int, str, str, int]:
    """Stable, bounded priority based solely on already-observed outcomes."""
    uncovered = sum(
        1
        for need_id in work_item.run_context.information_need_ids
        if evidence_counts_by_need.get(need_id, 0) == 0
    )
    productivity_rank = 0 if state.productive_calls > 0 else 1
    return (
        1 if state.repeated_zero_yield else 0,
        state.depth_calls,
        -uncovered,
        productivity_rank,
        work_item.primary_need_id,
        work_item.source.id,
        work_item.chunk_index,
    )


def select_next_adaptive_depth(
    pending: list[EvidenceExtractionWorkItem],
    *,
    states: dict[str, SourceOutcomeState],
    evidence_counts_by_need: dict[str, int],
) -> tuple[EvidenceExtractionWorkItem, str]:
    """Select one deterministic depth item after first-opportunity fairness."""
    selected = min(
        pending,
        key=lambda item: adaptive_depth_selection_key(
            item,
            state=states[item.source.id],
            evidence_counts_by_need=evidence_counts_by_need,
        ),
    )
    state = states[selected.source.id]
    if state.repeated_zero_yield:
        reason = SELECTION_DEPRIORITIZED_EMPTY_DEPTH
    elif state.productive_calls > 0:
        reason = SELECTION_PRODUCTIVE_DEPTH
    else:
        reason = SELECTION_EXPLORATORY_DEPTH
    return selected, reason


@dataclass(frozen=True)
class _PreparedSource:
    source: Source
    run_context: RunScopedSourceContext
    primary_need_id: str
    chunks: tuple[SourceContentChunk, ...]


def _dedupe_eligible_sources(sources: list[Source]) -> list[Source]:
    """Deterministic Source identity dedupe: id first, then canonical_url."""
    by_id: dict[str, Source] = {}
    for source in sorted(sources, key=lambda item: item.id):
        if source.id in by_id:
            continue
        by_id[source.id] = source

    by_canonical: dict[str, Source] = {}
    ordered: list[Source] = []
    for source in sorted(by_id.values(), key=lambda item: item.id):
        canonical = (source.canonical_url or source.url or source.id).strip()
        if canonical in by_canonical:
            continue
        by_canonical[canonical] = source
        ordered.append(source)
    return ordered


def _round_robin_need_buckets(
    buckets: dict[str, list[EvidenceExtractionWorkItem]],
) -> list[EvidenceExtractionWorkItem]:
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


def _prepare_sources(
    sources: list[Source],
    *,
    design: ResearchDesign,
    workflow_run_id: str,
    research_design_id: str,
    chunk_chars: int,
    overlap_chars: int,
) -> list[_PreparedSource]:
    prepared: list[_PreparedSource] = []
    for source in _dedupe_eligible_sources(sources):
        if not str(source.content_text or "").strip():
            continue
        run_context = resolve_run_scoped_context(
            source=source,
            design=design,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )
        if not run_context.information_need_ids:
            continue
        primary_need_id = sorted(run_context.information_need_ids)[0]
        chunks = split_normalized_source_content(
            source.content_text,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )
        if not chunks:
            continue
        prepared.append(
            _PreparedSource(
                source=source,
                run_context=run_context,
                primary_need_id=primary_need_id,
                chunks=tuple(chunks),
            ),
        )
    return prepared


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
    Build a deterministic coverage-before-depth Evidence extraction queue.

    PROPERTY V (P1-17.1): every eligible Source receives one first-chunk
    opportunity before any Source receives repeated chunk depth, subject only
    to the caller's Evidence/global budget stop.

    Phase 1 — first opportunity:
      one first chunk per eligible Source, interleaved need-fair across
      sorted primary InformationNeed IDs (sources ordered by id within a need).

    Phase 2 — depth:
      remaining chunks with the same need-fair round-robin, preserving
      source-id order within each need bucket.
    """
    prepared = _prepare_sources(
        sources,
        design=design,
        workflow_run_id=workflow_run_id,
        research_design_id=research_design_id,
        chunk_chars=chunk_chars,
        overlap_chars=overlap_chars,
    )
    if not prepared:
        return []

    first_buckets: dict[str, list[EvidenceExtractionWorkItem]] = {}
    for item in prepared:
        first_buckets.setdefault(item.primary_need_id, []).append(
            EvidenceExtractionWorkItem(
                source=item.source,
                chunk=item.chunks[0],
                run_context=item.run_context,
                phase=PHASE_FIRST_OPPORTUNITY,
                source_first_attempt=True,
                chunk_index=0,
                primary_need_id=item.primary_need_id,
            ),
        )
    phase1 = _round_robin_need_buckets(first_buckets)

    depth_buckets: dict[str, list[EvidenceExtractionWorkItem]] = {}
    for item in prepared:
        for chunk_index, chunk in enumerate(item.chunks[1:], start=1):
            depth_buckets.setdefault(item.primary_need_id, []).append(
                EvidenceExtractionWorkItem(
                    source=item.source,
                    chunk=chunk,
                    run_context=item.run_context,
                    phase=PHASE_DEPTH,
                    source_first_attempt=False,
                    chunk_index=chunk_index,
                    primary_need_id=item.primary_need_id,
                ),
            )
    phase2 = _round_robin_need_buckets(depth_buckets)
    return phase1 + phase2
