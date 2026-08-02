from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_source_text(text: str) -> str:
    """Collapse whitespace for deterministic substring grounding checks."""
    return _WHITESPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True)
class SourceLocator:
    normalized_start: int
    normalized_end: int
    excerpt_hash: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "normalized_start": self.normalized_start,
            "normalized_end": self.normalized_end,
            "excerpt_hash": self.excerpt_hash,
        }


def excerpt_hash(excerpt: str) -> str:
    return hashlib.sha256(normalize_source_text(excerpt).encode("utf-8")).hexdigest()


def locate_excerpt(
    *,
    source_text: str,
    excerpt: str,
    search_start: int = 0,
    search_end: int | None = None,
) -> SourceLocator | None:
    normalized_source = normalize_source_text(source_text)
    normalized_excerpt = normalize_source_text(excerpt)
    if not normalized_excerpt:
        return None
    end_bound = len(normalized_source) if search_end is None else search_end
    start = normalized_source.find(normalized_excerpt, search_start)
    while start >= 0:
        end = start + len(normalized_excerpt)
        if end <= end_bound:
            return SourceLocator(
                normalized_start=start,
                normalized_end=end,
                excerpt_hash=excerpt_hash(normalized_excerpt),
            )
        start = normalized_source.find(normalized_excerpt, start + 1)
    return None


def verify_grounding(
    *,
    source_text: str,
    excerpt: str,
    chunk_normalized_start: int | None = None,
    chunk_normalized_end: int | None = None,
) -> SourceLocator:
    from application.evidence.exceptions import UngroundedEvidenceError

    search_start = chunk_normalized_start or 0
    search_end = chunk_normalized_end
    locator = locate_excerpt(
        source_text=source_text,
        excerpt=excerpt,
        search_start=search_start,
        search_end=search_end,
    )
    if locator is None:
        locator = locate_excerpt(source_text=source_text, excerpt=excerpt)
    if locator is None:
        raise UngroundedEvidenceError(
            "source_excerpt is not present in acquired source content",
        )
    return locator
