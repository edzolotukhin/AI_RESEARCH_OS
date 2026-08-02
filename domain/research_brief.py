from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ResearchBrief:
    """
    Canonical Desk Research input specification owned by Project.

    Immutable value object; mutating project intent creates a new instance.
    """

    title: str
    business_question: str
    objectives: tuple[str, ...] = ()
    geography: tuple[str, ...] = ()
    market: str = ""
    target_entities: tuple[str, ...] = ()
    timeframe: str = ""
    constraints: tuple[str, ...] = ()
    deliverables: tuple[str, ...] = ()
    language: str = "en"
    context: str = ""
    known_information: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "business_question": self.business_question,
            "objectives": list(self.objectives),
            "geography": list(self.geography),
            "market": self.market,
            "target_entities": list(self.target_entities),
            "timeframe": self.timeframe,
            "constraints": list(self.constraints),
            "deliverables": list(self.deliverables),
            "language": self.language,
            "context": self.context,
            "known_information": list(self.known_information),
            "exclusions": list(self.exclusions),
        }

    def to_fingerprint_dict(self) -> dict[str, Any]:
        """Semantic payload for PF-07 idempotency fingerprinting."""
        return self.to_dict()

    def normalized_objectives(self) -> tuple[str, ...]:
        """Deterministic objective identities for traceability checks."""
        return tuple(normalize_objective_text(objective) for objective in self.objectives)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> ResearchBrief | None:
        if payload is None:
            return None
        if _is_legacy_project_brief(payload):
            return _from_legacy_project_brief(payload)
        return cls(
            title=str(payload.get("title", "")),
            business_question=str(payload.get("business_question", "")),
            objectives=_tuple_of_str(payload.get("objectives")),
            geography=_tuple_of_str(payload.get("geography")),
            market=str(payload.get("market", "")),
            target_entities=_tuple_of_str(payload.get("target_entities")),
            timeframe=str(payload.get("timeframe", "")),
            constraints=_tuple_of_str(payload.get("constraints")),
            deliverables=_tuple_of_str(payload.get("deliverables")),
            language=str(payload.get("language", "en") or "en"),
            context=str(payload.get("context", "")),
            known_information=_tuple_of_str(payload.get("known_information")),
            exclusions=_tuple_of_str(payload.get("exclusions")),
        )


def normalize_objective_text(value: str) -> str:
    """Stable normalized form for objective_refs and brief objectives."""
    return " ".join(value.lower().split())


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


def _is_legacy_project_brief(payload: dict[str, Any]) -> bool:
    return "business_problem" in payload or "research_goal" in payload


def _from_legacy_project_brief(payload: dict[str, Any]) -> ResearchBrief:
    objectives = _tuple_of_str(payload.get("research_objectives"))
    if not objectives and payload.get("research_goal"):
        objectives = (str(payload["research_goal"]).strip(),)

    geography = _tuple_of_str(payload.get("geography"))
    target_entities: list[str] = []
    for key in ("research_object", "target_audience"):
        value = str(payload.get(key, "")).strip()
        if value:
            target_entities.append(value)

    context_parts = [
        str(payload.get("client", "")).strip(),
        str(payload.get("comments", "")).strip(),
    ]
    context = " ".join(part for part in context_parts if part)

    return ResearchBrief(
        title=str(payload.get("project_title") or payload.get("title") or ""),
        business_question=str(
            payload.get("business_problem")
            or payload.get("business_question")
            or "",
        ),
        objectives=objectives,
        geography=geography,
        target_entities=tuple(target_entities),
        timeframe=str(payload.get("timeline") or payload.get("timeframe") or ""),
        constraints=_tuple_of_str(payload.get("constraints")),
        language=str(payload.get("language", "en") or "en"),
        context=context,
    )


def research_brief_field_names() -> tuple[str, ...]:
    return tuple(field.name for field in fields(ResearchBrief))
