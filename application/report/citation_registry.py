from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.evidence.evidence import Evidence
from domain.sources.source import Source


@dataclass(frozen=True)
class CitationEntry:
    citation_id: str
    source_id: str
    title: str
    canonical_url: str
    published_at: str | None
    retrieved_at: str
    source_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "source_id": self.source_id,
            "title": self.title,
            "canonical_url": self.canonical_url,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "source_type": self.source_type,
        }


class CitationRegistry:
    """Application-owned citation numbering for report sections."""

    def __init__(self) -> None:
        self._source_to_id: dict[str, str] = {}
        self._entries: dict[str, CitationEntry] = {}
        self._counter = 0

    def register_source(self, source: Source) -> str:
        if source.id in self._source_to_id:
            return self._source_to_id[source.id]
        self._counter += 1
        citation_id = f"S{self._counter}"
        entry = CitationEntry(
            citation_id=citation_id,
            source_id=source.id,
            title=source.title,
            canonical_url=source.canonical_url,
            published_at=source.published_at,
            retrieved_at=source.retrieved_at,
            source_type=source.source_type,
        )
        self._source_to_id[source.id] = citation_id
        self._entries[citation_id] = entry
        return citation_id

    def register_evidence(
        self,
        evidence: Evidence,
        *,
        sources_by_id: dict[str, Source],
    ) -> str | None:
        source = sources_by_id.get(evidence.source_id)
        if source is None:
            return None
        return self.register_source(source)

    def citation_ids_for_evidence_refs(
        self,
        evidence_refs: tuple[str, ...],
        *,
        evidence_by_id: dict[str, Evidence],
        sources_by_id: dict[str, Source],
    ) -> tuple[str, ...]:
        ids: list[str] = []
        seen: set[str] = set()
        for evidence_id in sorted(evidence_refs):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            citation_id = self.register_evidence(
                evidence,
                sources_by_id=sources_by_id,
            )
            if citation_id is None or citation_id in seen:
                continue
            seen.add(citation_id)
            ids.append(citation_id)
        return tuple(ids)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            citation_id: entry.to_dict()
            for citation_id, entry in sorted(self._entries.items())
        }
