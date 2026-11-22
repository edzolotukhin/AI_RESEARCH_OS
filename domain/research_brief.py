from __future__ import annotations

import dataclasses
from dataclasses import dataclass, fields
import hashlib
import json
from typing import Any


BRIEF_FINGERPRINT_V1 = "v1"
BRIEF_FINGERPRINT_V2 = "v2"


@dataclass(frozen=True)
class BriefObjective:
    objective_id: str
    ordinal: int
    text: str
    text_fingerprint: str

    @classmethod
    def create(cls, *, ordinal: int, text: str) -> "BriefObjective":
        normalized = str(text).strip()
        if not normalized:
            raise ValueError("Brief objective text must not be empty")
        if ordinal < 1:
            raise ValueError("Brief objective ordinal must be positive")
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return cls(
            objective_id=f"obj-{ordinal:03d}",
            ordinal=ordinal,
            text=normalized,
            text_fingerprint=fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "ordinal": self.ordinal,
            "text": self.text,
            "text_fingerprint": self.text_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BriefObjective":
        return cls(
            objective_id=str(payload["objective_id"]),
            ordinal=int(payload["ordinal"]),
            text=str(payload["text"]),
            text_fingerprint=str(payload["text_fingerprint"]),
        )


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
    objective_registry: tuple[BriefObjective, ...] | None = None
    fingerprint_version: str = BRIEF_FINGERPRINT_V1

    def to_dict(self) -> dict[str, Any]:
        payload = {
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
        if self.objective_registry is not None:
            payload["objective_registry"] = [
                item.to_dict() for item in self.objective_registry
            ]
            payload["fingerprint_version"] = self.fingerprint_version
        return payload

    def to_fingerprint_dict(self) -> dict[str, Any]:
        """Semantic payload for PF-07 idempotency fingerprinting."""
        payload = self.to_dict()
        if self.objective_registry is None:
            return payload
        return payload

    def materialize_objective_registry(self) -> "ResearchBrief":
        if self.objective_registry is not None:
            return self
        registry = tuple(
            BriefObjective.create(ordinal=index, text=text)
            for index, text in enumerate(self.objectives, start=1)
        )
        return dataclasses.replace(
            self,
            objective_registry=registry,
            fingerprint_version=BRIEF_FINGERPRINT_V2,
        )

    def normalized_objectives(self) -> tuple[str, ...]:
        """Deterministic objective identities for traceability checks."""
        return tuple(normalize_objective_text(objective) for objective in self.objectives)

    @property
    def objective_registry_identity(self) -> str:
        if self.objective_registry is None:
            return ""
        encoded = json.dumps(
            [item.to_dict() for item in self.objective_registry],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

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
            objective_registry=(
                tuple(
                    BriefObjective.from_dict(item)
                    for item in payload["objective_registry"]
                )
                if isinstance(payload.get("objective_registry"), list)
                else None
            ),
            fingerprint_version=str(
                payload.get("fingerprint_version", BRIEF_FINGERPRINT_V1)
            ),
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
