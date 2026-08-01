from __future__ import annotations

from typing import Any

from domain.research_brief import ResearchBrief


def normalize_research_brief_payload(payload: dict[str, Any]) -> ResearchBrief:
    """
    Normalize external request data into a canonical ResearchBrief.

    Trims strings, normalizes list fields, and applies default language.
    """
    language = str(payload.get("language", "en") or "en").strip().lower()
    if len(language) > 2:
        language = language[:2]

    return ResearchBrief(
        title=str(payload.get("title", "")).strip(),
        business_question=str(payload.get("business_question", "")).strip(),
        objectives=_normalize_string_list(payload.get("objectives")),
        geography=_normalize_string_list(payload.get("geography")),
        market=str(payload.get("market", "")).strip(),
        target_entities=_normalize_string_list(payload.get("target_entities")),
        timeframe=str(payload.get("timeframe", "")).strip(),
        constraints=_normalize_string_list(payload.get("constraints")),
        deliverables=_normalize_string_list(payload.get("deliverables")),
        language=language or "en",
        context=str(payload.get("context", "")).strip(),
        known_information=_normalize_string_list(payload.get("known_information")),
        exclusions=_normalize_string_list(payload.get("exclusions")),
    )


def _normalize_string_list(value: Any) -> tuple[str, ...]:
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
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return tuple(normalized)
    return ()
