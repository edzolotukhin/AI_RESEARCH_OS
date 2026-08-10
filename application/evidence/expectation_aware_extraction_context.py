from __future__ import annotations

from typing import Any

from domain.planning.research_design import InformationNeed

EXTRACTION_SYSTEM_GUIDANCE = (
    "Extract grounded research evidence from the provided source text chunk. "
    "Return JSON only with shape "
    '{"items":[{"statement":"...","source_excerpt":"...",'
    '"information_need_id":"...","evidence_type":"direct_excerpt",'
    '"direct":true,"confidence":0.8}]}. '
    "source_excerpt MUST be an exact substring of source_text after "
    "whitespace normalization. Do not invent IDs beyond "
    "information_need_id values listed in information_needs. "
    "When an information need includes required_aspects or other "
    "evidence_expectation fields, prefer source-grounded excerpts relevant "
    "to those aspects, geography, timeframe, and stated nature. "
    "Do not fabricate facts, aspect coverage, or quantitative values absent "
    "from source_text. Returning {\"items\":[]} is valid when the chunk has "
    "no relevant grounded evidence. "
    "If requires_quantitative_evidence is true, preferentially extract "
    "grounded quantitative facts when they exist; still extract useful "
    "qualitative evidence; never invent numbers. "
    "Do not assess sufficiency, readiness, or whether aspects are satisfied. "
    "Do not treat this single-source extraction as satisfying a multi-source "
    "independence quota."
)


def build_extraction_need_payload(need: InformationNeed) -> dict[str, Any]:
    """LLM-facing InformationNeed context. Omits fake EE for legacy needs."""
    payload: dict[str, Any] = {
        "id": need.id,
        "research_question_id": need.research_question_id,
        "description": need.description,
    }
    expectation = need.evidence_expectation
    if expectation is None:
        return payload

    payload["nature"] = expectation.nature.value
    payload["required_aspects"] = list(expectation.required_aspects)
    payload["requires_quantitative_evidence"] = (
        expectation.requires_quantitative_evidence
    )
    geography = expectation.geography or (str(need.geography or "").strip() or None)
    timeframe = expectation.timeframe or (str(need.timeframe or "").strip() or None)
    if geography:
        payload["geography"] = geography
    if timeframe:
        payload["timeframe"] = timeframe
    return payload


def format_extraction_need_line(need: dict[str, Any]) -> str:
    line = (
        f"- id={need['id']} question_id={need['research_question_id']} "
        f"description={need['description']}"
    )
    if "required_aspects" not in need and "nature" not in need:
        return line
    extras: list[str] = []
    if "nature" in need:
        extras.append(f"nature={need['nature']}")
    if "required_aspects" in need:
        extras.append(
            "required_aspects=" + ",".join(str(item) for item in need["required_aspects"]),
        )
    if need.get("geography"):
        extras.append(f"geography={need['geography']}")
    if need.get("timeframe"):
        extras.append(f"timeframe={need['timeframe']}")
    if "requires_quantitative_evidence" in need:
        extras.append(
            "requires_quantitative_evidence="
            + str(need["requires_quantitative_evidence"]).lower(),
        )
    if extras:
        line = f"{line} {' '.join(extras)}"
    return line
