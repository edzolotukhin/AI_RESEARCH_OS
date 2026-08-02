from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceCandidate:
    """Transient search result before retrieval and durable persistence."""

    provider: str
    url: str
    title: str
    snippet: str
    query_id: str
    rank: int
    provider_result_id: str | None = None
    published_at: str | None = None
    source_type: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_result_id": self.provider_result_id,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "source_type": self.source_type,
            "rank": self.rank,
            "query_id": self.query_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceCandidate:
        metadata = payload.get("metadata") or {}
        return cls(
            provider=str(payload["provider"]),
            provider_result_id=(
                str(payload["provider_result_id"])
                if payload.get("provider_result_id") is not None
                else None
            ),
            url=str(payload["url"]),
            title=str(payload.get("title", "")),
            snippet=str(payload.get("snippet", "")),
            published_at=(
                str(payload["published_at"])
                if payload.get("published_at") is not None
                else None
            ),
            source_type=(
                str(payload["source_type"])
                if payload.get("source_type") is not None
                else None
            ),
            rank=int(payload.get("rank", 0)),
            query_id=str(payload["query_id"]),
            metadata={str(k): str(v) for k, v in metadata.items()},
        )
