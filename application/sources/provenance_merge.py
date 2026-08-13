from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source


def merge_refs(*parts: tuple[str, ...]) -> tuple[str, ...]:
    """Merge reference tuples with stable first-seen order and uniqueness."""
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for value in part:
            if not value or value in seen:
                continue
            merged.append(value)
            seen.add(value)
    return tuple(merged)


def is_successful_acquisition(status: RetrievalStatus) -> bool:
    """Statuses that satisfy the search task minimum acquisition threshold."""
    return status in {RetrievalStatus.ACQUIRED, RetrievalStatus.TRUNCATED}


def has_immutable_acquired_content(source: Source) -> bool:
    return is_successful_acquisition(source.retrieval_status) and bool(
        source.content_text or source.content_checksum,
    )


@dataclass(frozen=True)
class ProvenanceDelta:
    workflow_run_id: str
    research_design_id: str
    query_refs: tuple[str, ...]
    research_question_refs: tuple[str, ...]
    information_need_refs: tuple[str, ...]
    discovery_records: tuple[dict[str, Any], ...]


def build_discovery_record(
    *,
    provider: str,
    query_id: str,
    rank: int,
    workflow_run_id: str,
    research_design_id: str,
    research_question_id: str = "",
    information_need_id: str = "",
    retrieval_arm: str = "baseline",
    provider_country: str = "",
    provider_query_text: str = "",
    provider_result_count: str = "",
) -> dict[str, Any]:
    return {
        "provider": provider,
        "query_id": query_id,
        "rank": rank,
        "workflow_run_id": workflow_run_id,
        "research_design_id": research_design_id,
        "research_question_id": research_question_id,
        "information_need_id": information_need_id,
        "retrieval_arm": retrieval_arm,
        "provider_country": provider_country,
        "provider_query_text": provider_query_text,
        "provider_result_count": provider_result_count,
    }


def merge_discovery_records(
    existing: list[dict[str, Any]],
    additions: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {
        (
            str(item.get("provider", "")),
            str(item.get("query_id", "")),
            str(item.get("workflow_run_id", "")),
            str(item.get("research_design_id", "")),
            str(item.get("rank", "")),
            str(item.get("retrieval_arm", "baseline")),
        )
        for item in merged
    }
    for record in additions:
        key = (
            str(record.get("provider", "")),
            str(record.get("query_id", "")),
            str(record.get("workflow_run_id", "")),
            str(record.get("research_design_id", "")),
            str(record.get("rank", "")),
            str(record.get("retrieval_arm", "baseline")),
        )
        if key in seen:
            continue
        merged.append(dict(record))
        seen.add(key)
    return merged


def apply_provenance_delta(existing: Source, delta: ProvenanceDelta) -> Source:
    """Merge provenance onto an existing Source without rewriting acquired content."""
    existing.workflow_run_refs = merge_refs(
        existing.workflow_run_refs,
        (delta.workflow_run_id,),
    )
    existing.research_design_refs = merge_refs(
        existing.research_design_refs,
        (delta.research_design_id,),
    )
    existing.query_refs = merge_refs(existing.query_refs, delta.query_refs)
    existing.research_question_refs = merge_refs(
        existing.research_question_refs,
        delta.research_question_refs,
    )
    existing.information_need_refs = merge_refs(
        existing.information_need_refs,
        delta.information_need_refs,
    )
    metadata = dict(existing.metadata)
    metadata["discovery_records"] = merge_discovery_records(
        list(metadata.get("discovery_records") or []),
        delta.discovery_records,
    )
    existing.metadata = metadata
    return existing


def discovery_record_key(record: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(record.get("provider", "")),
        str(record.get("query_id", "")),
        str(record.get("workflow_run_id", "")),
        str(record.get("research_design_id", "")),
        str(record.get("rank", "")),
        str(record.get("retrieval_arm", "baseline")),
    )


def has_discovery_record(
    existing_records: list[dict[str, Any]],
    record: dict[str, Any],
) -> bool:
    target = discovery_record_key(record)
    return any(discovery_record_key(item) == target for item in existing_records)


def missing_discovery_records(
    existing: Source,
    additions: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    existing_records = list(existing.metadata.get("discovery_records") or [])
    return tuple(
        record
        for record in additions
        if not has_discovery_record(existing_records, record)
    )


def apply_first_acquisition(existing: Source, incoming: Source) -> Source:
    """
    Populate factual content on a source that has not yet succeeded.

    Once content is acquired, later merges must use apply_provenance_delta only.
    """
    if has_immutable_acquired_content(existing):
        return existing
    if not is_successful_acquisition(incoming.retrieval_status):
        return existing
    existing.url = incoming.url
    existing.title = incoming.title
    existing.publisher = incoming.publisher
    existing.author = incoming.author
    existing.published_at = incoming.published_at
    existing.retrieved_at = incoming.retrieved_at
    existing.source_type = incoming.source_type
    existing.language = incoming.language
    existing.content_type = incoming.content_type
    existing.retrieval_status = incoming.retrieval_status
    existing.content_text = incoming.content_text
    existing.content_checksum = incoming.content_checksum
    incoming_metadata = dict(incoming.metadata)
    existing_metadata = dict(existing.metadata)
    existing_metadata.update(incoming_metadata)
    existing.metadata = existing_metadata
    return existing
