from __future__ import annotations

import json
from typing import Any

from domain.planning.research_design import InformationNeed

EXTRACTION_SYSTEM_GUIDANCE = (
    "Extract grounded research evidence from the provided source text chunk. "
    "Return JSON only with shape "
    '{"items":[{"statement":"...","source_excerpt":"...",'
    '"information_need_id":"...","evidence_type":"direct_excerpt",'
    '"direct":true,"confidence":0.8,'
    '"observation_period":null,"data_origin_id":null,'
    '"data_origin_excerpt":null}]}. '
    "source_excerpt MUST be an exact substring of source_text after "
    "whitespace normalization. Do not invent IDs beyond "
    "information_need_id values listed in information_needs. "
    "When an information need includes required_aspects or other "
    "evidence_expectation fields, prefer source-grounded excerpts relevant "
    "to those aspects, geography, timeframe, and stated nature. "
    "Do not fabricate facts, aspect coverage, or quantitative values absent "
    "from source_text. Returning {\"items\":[]} is valid when the chunk has "
    "no relevant grounded evidence. "
    "observation_period is the exact date/month/quarter/year or range of the "
    "factual observation, copied verbatim from source_excerpt; use null when "
    "unknown. It is NOT the page publication or retrieval date. "
    "For a forecast, retain its future reference period and identify it as "
    "a forecast in the statement. "
    "data_origin_id is the named underlying dataset/provider for this "
    "particular claim, not the web publisher by default. Use null when "
    "dependency is not explicit. data_origin_excerpt must quote the exact "
    "source_text passage establishing that relationship; otherwise null. "
    "If requires_quantitative_evidence is true, preferentially extract "
    "grounded quantitative facts when they exist; still extract useful "
    "qualitative evidence; never invent numbers. "
    "Do not assess sufficiency, readiness, or whether aspects are satisfied. "
    "Do not treat this single-source extraction as satisfying a multi-source "
    "independence quota."
)

V2_EXTRACTION_SYSTEM_GUIDANCE = (
    " Each item must include contract_version=desk_evidence_candidate_v2 and "
    "required_aspect_refs (zero to eight unique supplied IDs), subject_binding with "
    "binding_type canonical_subject or supporting_relation, the supplied subject_id, "
    "the supplied subject_fingerprint, "
    "and supporting_relation_id only for a relation binding; semantic_justification "
    "of at most 500 characters; and geography_applicability using only supplied values. "
    "Select identifiers only from extraction_vocabulary. An identifier is structural "
    "scope, never permission to invent support. The exact excerpt must support the "
    "statement and every assigned aspect."
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


def build_extraction_vocabulary(*, design, needs_payload: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_need_ids = {str(item["id"]) for item in needs_payload}
    subject = design.research_subject
    if subject is None:
        return {"subject": None, "information_needs": needs_payload}
    relations = []
    for relation in subject.supporting_relations:
        scoped_needs = tuple(
            ref for ref in relation.information_need_refs if ref in allowed_need_ids
        )
        if not scoped_needs:
            continue
        relations.append({
            "relation_id": relation.relation_id,
            "relation_type": relation.relation_type,
            "information_need_refs": list(scoped_needs),
            "research_question_refs": list(relation.research_question_refs),
            "required_aspect_refs": list(relation.required_aspect_refs),
            "concepts": list(relation.concepts),
            "approved_representations": [
                {
                    "language": item.language,
                    "label": item.label,
                    "normalized_phrases": list(item.normalized_phrases),
                }
                for item in relation.lexical_representations
                if item.approval_status.value == "approved"
            ],
        })
    return {
        "subject": {
            "subject_id": subject.subject_id,
            "subject_fingerprint": subject.semantic_fingerprint,
            "canonical_label": subject.canonical_label,
            "canonical_language": subject.canonical_language,
            "approved_representations": [
                {
                    "language": item.language,
                    "label": item.label,
                    "normalized_phrases": list(item.normalized_phrases),
                }
                for item in subject.approved_representations
            ],
            "supporting_relations": relations,
            "exclusions": list(subject.exclusions),
        },
        "information_needs": needs_payload,
    }


def format_extraction_vocabulary(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
