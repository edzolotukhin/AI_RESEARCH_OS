from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ResearchQuestion:
    """Semantic research question within a desk research design."""

    id: str
    question: str
    # Exact brief objective text; matched via normalize_objective_text().
    objective_refs: tuple[str, ...] = ()
    priority: int = 1
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "objective_refs": list(self.objective_refs),
            "priority": self.priority,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchQuestion:
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            objective_refs=_tuple_of_str(payload.get("objective_refs")),
            priority=int(payload.get("priority", 1)),
            rationale=str(payload.get("rationale", "")),
        )


@dataclass(frozen=True)
class InformationNeed:
    """Information required to answer a research question (DR-03 prep)."""

    id: str
    research_question_id: str
    description: str
    priority: int = 1
    preferred_source_types: tuple[str, ...] = ()
    timeframe: str = ""
    geography: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "research_question_id": self.research_question_id,
            "description": self.description,
            "priority": self.priority,
            "preferred_source_types": list(self.preferred_source_types),
            "timeframe": self.timeframe,
            "geography": self.geography,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InformationNeed:
        return cls(
            id=str(payload["id"]),
            research_question_id=str(payload["research_question_id"]),
            description=str(payload["description"]),
            priority=int(payload.get("priority", 1)),
            preferred_source_types=_tuple_of_str(
                payload.get("preferred_source_types"),
            ),
            timeframe=str(payload.get("timeframe", "")),
            geography=str(payload.get("geography", "")),
        )


@dataclass(frozen=True)
class ResearchDesign:
    """
    Semantic desk research design: how a brief will be investigated.

    Not the runtime workflow, search results, or deliverable artifacts.
    """

    id: str
    research_questions: tuple[ResearchQuestion, ...]
    information_needs: tuple[InformationNeed, ...] = ()
    source_strategy: tuple[str, ...] = ()
    analysis_plan: tuple[str, ...] = ()
    deliverable_plan: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "research_questions": [
                question.to_dict() for question in self.research_questions
            ],
            "information_needs": [
                need.to_dict() for need in self.information_needs
            ],
            "source_strategy": list(self.source_strategy),
            "analysis_plan": list(self.analysis_plan),
            "deliverable_plan": list(self.deliverable_plan),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ResearchDesign | None:
        if payload is None:
            return None
        return cls(
            id=str(payload.get("id") or uuid4()),
            research_questions=tuple(
                ResearchQuestion.from_dict(item)
                for item in payload.get("research_questions", [])
            ),
            information_needs=tuple(
                InformationNeed.from_dict(item)
                for item in payload.get("information_needs", [])
            ),
            source_strategy=_tuple_of_str(payload.get("source_strategy")),
            analysis_plan=_tuple_of_str(payload.get("analysis_plan")),
            deliverable_plan=_tuple_of_str(payload.get("deliverable_plan")),
            assumptions=_tuple_of_str(payload.get("assumptions")),
            limitations=_tuple_of_str(payload.get("limitations")),
            language=str(payload.get("language", "en") or "en"),
        )


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, list):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return tuple(normalized)
    return ()


def research_design_field_names() -> tuple[str, ...]:
    return tuple(field.name for field in fields(ResearchDesign))
