"""Read-only, fail-closed validation of persisted canonical citation spans.

Offsets are half-open Python Unicode character indices into the full persisted
source after the one canonical HTML/NFC/whitespace normalization. They are not
bytes, UTF-16 units, raw HTML offsets or chunk-relative offsets. Validation never
searches for a replacement span or mutates historical Evidence.
"""
from hashlib import sha256

from application.evidence.grounding import normalize_source_text, excerpt_hash


def citation_is_valid(evidence, source) -> bool:
    if source is None or source.id != evidence.source_id or source.project_id != evidence.project_id:
        return False
    if not source.content_text or not source.content_checksum:
        return False
    if evidence.source_content_checksum != source.content_checksum:
        return False
    if sha256(source.content_text.encode("utf-8")).hexdigest() != source.content_checksum:
        return False
    locator = evidence.source_locator
    if not isinstance(locator, dict):
        return False
    start, end = locator.get("normalized_start"), locator.get("normalized_end")
    text = normalize_source_text(source.content_text)
    excerpt = normalize_source_text(evidence.source_excerpt)
    return (
        type(start) is int and type(end) is int
        and 0 <= start < end <= len(text)
        and bool(excerpt) and text[start:end] == excerpt
        and locator.get("excerpt_hash") == excerpt_hash(evidence.source_excerpt)
    )


def citation_valid_evidence(evidence, source_repository):
    """Missing source access cannot certify truth; raw repositories remain readable."""
    from application import research_funnel_telemetry as funnel
    sources = {}
    result = []
    for item in evidence:
        if item.source_id not in sources:
            sources[item.source_id] = (
                source_repository.get_by_id(item.source_id) if source_repository is not None else None
            )
        if citation_is_valid(item, sources[item.source_id]):
            result.append(item)
        else:
            for ref in item.information_need_refs:
                funnel.qualification(item.id, ref, False, "invalid_citation",
                                     policy="canonical_citation_filter")
    return tuple(result)
