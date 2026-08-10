"""Need-specific source exhaustion for targeted remediation (P1-07.14.1).

A source is exhausted for InformationNeed Y only when extraction completed a
valid zero-yield outcome for (source, Y) and zero grounded Evidence rows
persisted for that pair.

Valid zero-yield:
- extractor_status == no_candidates after a completed valid empty result
  (including deterministic extractors with no inner-chunk shape)

Not exhausted (technical / incomplete / non-semantic):
- invalid_json / empty / incomplete / schema mismatch provider output
- extractor exception / timeout / retry / budget_stop / pending
- no_run_context
- bounded_partial remediations extraction (attempt envelope stopped early)
- extractor_status == success with candidates that failed grounding or
  other post-parse filters (conservative: attempt unusable, source not spent)

Non-zero Evidence is never exhausted here, even if Sufficiency remains
PARTIAL. Exhaustion is never global across needs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from application.execution.remediation_attempt_envelope import (
    EXTRACTION_BOUNDED_PARTIAL,
    SHARED_REMEDIATION_EXTRACTION_KEY,
)
from domain.evidence.evidence import Evidence
from domain.sources.source import Source

_TECHNICAL_WORK_ITEM_STATUSES = frozenset(
    {
        "exception",
        "budget_stop",
        "pending",
        "no_run_context",
    }
)
_TECHNICAL_INNER_STATUSES = frozenset({"exception", "budget_stop"})
# Mirror EvidenceResponseClassification failure outcomes; do not import evidence
# internals into the acquisition boundary.
_FAILURE_CLASSIFICATIONS = frozenset(
    {
        "empty_provider_output",
        "incomplete_provider_output",
        "invalid_json",
        "root_type_mismatch",
        "schema_contract_mismatch",
    }
)


def extraction_attempted_pairs(
    shared_state: Mapping[str, Any] | None,
) -> frozenset[tuple[str, str]]:
    """Return (source_id, information_need_id) pairs already sent to extraction."""
    pairs: set[tuple[str, str]] = set()
    for item in _work_items(shared_state):
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        for need_id in _need_ids(item):
            pairs.add((source_id, need_id))
    return frozenset(pairs)


def extraction_work_items(
    shared_state: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(_work_items(shared_state))


def work_item_is_valid_zero_yield(item: Mapping[str, Any]) -> bool:
    """True only for a completed valid empty extraction, not technical failure."""
    status = str(item.get("extractor_status") or "pending")
    if status in _TECHNICAL_WORK_ITEM_STATUSES:
        return False
    if item.get("exception_class"):
        return False
    if _has_technical_inner_failure(item):
        return False
    return status == "no_candidates"


def qualifying_zero_yield_source_need_pairs(
    work_items: Iterable[Mapping[str, Any]] | None,
) -> frozenset[tuple[str, str]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in work_items or ():
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        for need_id in _need_ids(item):
            grouped.setdefault((source_id, need_id), []).append(item)
    exhausted: set[tuple[str, str]] = set()
    for pair, items in grouped.items():
        if any(_is_bounded_partial_item(item) for item in items):
            continue
        if items and all(work_item_is_valid_zero_yield(item) for item in items):
            exhausted.add(pair)
    return frozenset(exhausted)


def grounded_evidence_count(
    evidence_rows: Sequence[Evidence],
    *,
    source_id: str,
    information_need_id: str,
    workflow_run_id: str | None = None,
) -> int:
    count = 0
    for row in evidence_rows:
        if row.source_id != source_id:
            continue
        if information_need_id not in (row.information_need_refs or ()):
            continue
        if workflow_run_id and row.workflow_run_id != workflow_run_id:
            continue
        count += 1
    return count


def exhausted_canonical_urls_for_need(
    *,
    information_need_id: str,
    sources: Iterable[Source],
    evidence_rows: Sequence[Evidence],
    work_items: Iterable[Mapping[str, Any]] | None = None,
    attempted_pairs: Iterable[tuple[str, str]] | None = None,
    workflow_run_id: str | None = None,
) -> frozenset[str]:
    if work_items is not None:
        qualified = qualifying_zero_yield_source_need_pairs(work_items)
    else:
        qualified = frozenset(attempted_pairs or ())
    exhausted: set[str] = set()
    for source in sources:
        if (source.id, information_need_id) not in qualified:
            continue
        if grounded_evidence_count(
            evidence_rows,
            source_id=source.id,
            information_need_id=information_need_id,
            workflow_run_id=workflow_run_id,
        ) > 0:
            continue
        if source.canonical_url:
            exhausted.add(source.canonical_url)
    return frozenset(exhausted)


def _work_items(shared_state: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not shared_state:
        return []
    items: list[Mapping[str, Any]] = []
    items.extend(_items_from_extraction_block(shared_state.get("evidence_extraction")))
    items.extend(
        _items_from_extraction_block(shared_state.get(SHARED_REMEDIATION_EXTRACTION_KEY)),
    )
    return items


def _items_from_extraction_block(block: object) -> list[Mapping[str, Any]]:
    if not isinstance(block, Mapping):
        return []
    diagnostics = block.get("diagnostics") or {}
    if not isinstance(diagnostics, Mapping):
        return []
    processing_state = diagnostics.get("extraction_processing_state")
    items: list[Mapping[str, Any]] = []
    for item in diagnostics.get("work_items") or []:
        if not isinstance(item, Mapping):
            continue
        merged = dict(item)
        if processing_state and not merged.get("source_processing_state"):
            merged["source_processing_state"] = processing_state
        items.append(merged)
    return items


def _is_bounded_partial_item(item: Mapping[str, Any]) -> bool:
    for key in ("source_processing_state", "extraction_processing_state"):
        if str(item.get(key) or "") == EXTRACTION_BOUNDED_PARTIAL:
            return True
    return False


def _need_ids(item: Mapping[str, Any]) -> list[str]:
    need_ids = item.get("information_need_ids") or []
    if isinstance(need_ids, str):
        need_ids = [need_ids]
    return [str(need_id).strip() for need_id in need_ids if str(need_id).strip()]


def _has_technical_inner_failure(item: Mapping[str, Any]) -> bool:
    for chunk in item.get("inner_chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        if str(chunk.get("extractor_status") or "") in _TECHNICAL_INNER_STATUSES:
            return True
        shape = chunk.get("response_shape") or {}
        if not isinstance(shape, Mapping):
            continue
        classification = str(shape.get("response_classification") or "")
        if classification in _FAILURE_CLASSIFICATIONS:
            return True
    return False
