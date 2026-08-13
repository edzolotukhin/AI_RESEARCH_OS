from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.sources.retrieval_arm import RetrievalArm


@dataclass(frozen=True)
class SearchQuery:
    """Provider-neutral search request derived from an InformationNeed."""

    id: str
    research_question_id: str
    information_need_id: str
    query_text: str
    language: str = "en"
    geography: str = ""
    timeframe: str = ""
    preferred_source_types: tuple[str, ...] = ()
    max_results: int = 5
    rationale: str = ""
    # Transient provider-facing projection. Intentionally excluded from
    # serialization so the complete query remains the durable semantic contract.
    provider_query_text: str = ""
    # Transient execution strategy. None preserves the pre-portfolio direct
    # adapter contract; production portfolio execution always sets an arm.
    retrieval_arm: RetrievalArm | None = None

    def __post_init__(self) -> None:
        if not self.query_text.strip():
            raise ValueError("SearchQuery.query_text must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "research_question_id": self.research_question_id,
            "information_need_id": self.information_need_id,
            "query_text": self.query_text,
            "language": self.language,
            "geography": self.geography,
            "timeframe": self.timeframe,
            "preferred_source_types": list(self.preferred_source_types),
            "max_results": self.max_results,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SearchQuery:
        return cls(
            id=str(payload["id"]),
            research_question_id=str(payload["research_question_id"]),
            information_need_id=str(payload["information_need_id"]),
            query_text=str(payload["query_text"]),
            language=str(payload.get("language", "en") or "en"),
            geography=str(payload.get("geography", "")),
            timeframe=str(payload.get("timeframe", "")),
            preferred_source_types=tuple(
                str(item) for item in payload.get("preferred_source_types", [])
            ),
            max_results=int(payload.get("max_results", 5)),
            rationale=str(payload.get("rationale", "")),
        )
