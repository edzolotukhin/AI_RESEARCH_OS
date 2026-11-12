"""Versioned identities for resources, extracted snapshots and discovery paths."""
from __future__ import annotations

from hashlib import sha256
import json

from application.sources.url_canonicalizer import canonicalize_url


def identity_digest(*parts: object) -> str:
    return sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def terminal_resource_key(project_id: str, terminal_url: str) -> str:
    """A changed response body does not change resource identity."""
    return identity_digest("terminal-resource-v1", project_id, canonicalize_url(terminal_url))


def acquisition_path_digest(*, project_id: str, landing_url: str,
                            terminal_url: str, navigation_chain: tuple[str, ...]) -> str:
    return identity_digest(
        "acquisition-path-v1", project_id, canonicalize_url(landing_url),
        tuple(canonicalize_url(url) for url in navigation_chain),
        canonicalize_url(terminal_url),
    )


def prepare_snapshot(source):
    source.terminal_resource_key = terminal_resource_key(source.project_id, source.url)
    if source.raw_checksum_kind not in {"sha256-bytes", "legacy-surrogate"}:
        raise ValueError("Unknown raw checksum kind")
    if source.raw_checksum_kind == "sha256-bytes":
        checksum = source.raw_content_checksum
        if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("Raw bytes require a SHA-256 checksum")
    else:
        # Includes status to prevent failed attempts aliasing a successful body.
        source.raw_content_checksum = identity_digest(
            "legacy-surrogate", source.retrieval_status.value,
            source.content_text, source.content_checksum,
        )
    if not source.extraction_revision or len(source.extraction_revision) > 64:
        raise ValueError("Invalid extraction revision")
    return source


IMMUTABLE_FIELDS = (
    "project_id", "url", "canonical_url", "title", "publisher", "author",
    "published_at", "retrieved_at", "source_type", "language", "content_type",
    "retrieval_status", "content_text", "content_checksum", "terminal_resource_key",
    "raw_content_checksum", "raw_checksum_kind", "content_revision", "extraction_revision",
)


def assert_snapshot_unchanged(existing, incoming):
    if any(getattr(existing, key) != getattr(incoming, key) for key in IMMUTABLE_FIELDS):
        raise ValueError("Source snapshot is immutable; create a new revision")
    # Discovery attribution is the only mutable legacy metadata field.
    def content_metadata(source):
        return {k: v for k, v in source.metadata.items() if k != "discovery_records"}
    if content_metadata(existing) != content_metadata(incoming):
        raise ValueError("Source extraction metadata is immutable")
