"""Exact whole-document identity, not similarity or source independence."""
import hashlib
from application.evidence.grounding import canonicalize_grounding_text

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source


def acquired_content_identity(source: Source) -> str:
    # An equal truncated prefix is not proof that two documents are identical.
    if source.retrieval_status != RetrievalStatus.ACQUIRED or source.metadata.get("truncated"):
        return ""
    normalized = canonicalize_grounding_text(source.content_text)
    if not normalized:
        return ""
    return "content-v1:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
