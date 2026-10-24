from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import ReportClaim
from domain.reports.report_section import ReportSection

_NUMBER = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)?%?(?![\w-])")


class ClaimRenderingError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedReport:
    sections: tuple[ReportSection, ...]
    summary_units: tuple[dict[str, Any], ...]
    executive_summary: str


def render_validated_claims(*, claims: tuple[ReportClaim, ...], design: ResearchDesign,
                            rendered_payload: dict[str, Any] | None = None,
                            summary_payload: dict[str, Any] | None = None) -> RenderedReport:
    claims_by_id = {item.claim_id: item for item in claims}
    rendered_payload = rendered_payload or _deterministic_sections(claims, design)
    sections = tuple(_validate_section(item, claims_by_id) for item in _require_array(rendered_payload, "sections"))
    if not sections:
        raise ClaimRenderingError("structured Report requires claim-bound sections")
    summary_payload = summary_payload or {"summary_units": [{"text": item.proposition, "claim_ids": [item.claim_id], "classification": "factual"} for item in claims[:3]]}
    units = tuple(_validate_unit(item, claims_by_id, field="summary_unit") for item in _require_array(summary_payload, "summary_units"))
    if not units:
        raise ClaimRenderingError("structured Report requires summary_units")
    return RenderedReport(sections, units, " ".join(str(item["text"]) for item in units))


def repair_missing_claim_sections(*, sections: tuple[ReportSection, ...],
                                  claims: tuple[ReportClaim, ...],
                                  required_rq_ids: tuple[str, ...],
                                  design: ResearchDesign) -> tuple[ReportSection, ...]:
    """One deterministic claim-bound repair pass; never creates authority."""
    covered = {rq for section in sections if section.claim_refs for rq in section.research_question_refs}
    missing = set(required_rq_ids) - covered
    if not missing:
        return sections
    payload = _deterministic_sections(tuple(claim for claim in claims if set(claim.research_question_ids) & missing), design)
    claims_by_id = {item.claim_id: item for item in claims}
    repairs = tuple(_validate_section(item, claims_by_id) for item in payload["sections"] if set(item["research_question_ids"]) & missing)
    return (*sections, *repairs)


def _deterministic_sections(claims: tuple[ReportClaim, ...], design: ResearchDesign) -> dict[str, Any]:
    sections = []
    for question in design.research_questions:
        selected = [claim for claim in claims if question.id in claim.research_question_ids]
        if not selected:
            continue
        sections.append({
            "section_id": str(uuid5(NAMESPACE_URL, f"claim-section:{question.id}:{','.join(item.claim_id for item in selected)}")),
            "title": f"{question.id}: {question.question[:80]}",
            "research_question_ids": [question.id],
            "claim_ids": [item.claim_id for item in selected],
            "paragraphs": [{"text": item.proposition, "claim_ids": [item.claim_id], "classification": "factual"} for item in selected],
        })
    return {"sections": sections}


def _validate_section(raw: Any, claims_by_id: dict[str, ReportClaim]) -> ReportSection:
    if not isinstance(raw, dict) or set(raw) != {"section_id", "title", "research_question_ids", "claim_ids", "paragraphs"}:
        raise ClaimRenderingError("invalid rendered section schema")
    claim_ids = _ids(raw["claim_ids"], field="section.claim_ids", required=True)
    selected = _claims(claim_ids, claims_by_id)
    paragraphs = tuple(_validate_unit(item, claims_by_id, field="paragraph") for item in raw["paragraphs"] if isinstance(item, dict)) if isinstance(raw["paragraphs"], list) else ()
    if not paragraphs or not any(item["classification"] == "factual" for item in paragraphs):
        raise ClaimRenderingError("substantive section requires a factual claim-bound paragraph")
    paragraph_claims = {claim_id for item in paragraphs for claim_id in item["claim_ids"]}
    if not paragraph_claims <= set(claim_ids):
        raise ClaimRenderingError("paragraph claims must belong to section")
    derived_rqs = tuple(sorted({rq for claim in selected for rq in claim.research_question_ids}))
    requested_rqs = _ids(raw["research_question_ids"], field="section.research_question_ids", required=True)
    if not set(requested_rqs) <= set(derived_rqs):
        raise ClaimRenderingError("section ResearchQuestion provenance conflicts with claims")
    content = "\n\n".join(str(item["text"]) for item in paragraphs)
    return ReportSection(id=str(raw["section_id"]), title=str(raw["title"]).strip(), content=content, research_question_refs=requested_rqs, finding_refs=tuple(sorted({item for claim in selected for item in claim.finding_ids})), insight_refs=tuple(sorted({item for claim in selected for item in claim.insight_ids})), evidence_refs=tuple(sorted({item for claim in selected for item in claim.evidence_ids})), citation_ids=tuple(sorted({item for claim in selected for item in claim.citation_ids})), claim_refs=claim_ids, metadata={"section_kind": "rq_answer", "structured_claim_contract": "desk_report_claim_v1", "paragraphs": list(paragraphs)})


def _validate_unit(raw: Any, claims_by_id: dict[str, ReportClaim], *, field: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"text", "claim_ids", "classification"}:
        raise ClaimRenderingError(f"invalid {field} schema")
    text = str(raw["text"]).strip(); classification = str(raw["classification"])
    if not text or classification not in {"factual", "non_factual"}:
        raise ClaimRenderingError(f"invalid {field}")
    claim_ids = _ids(raw["claim_ids"], field=f"{field}.claim_ids", required=classification == "factual")
    selected = _claims(claim_ids, claims_by_id)
    if classification == "non_factual" and claim_ids:
        raise ClaimRenderingError("non_factual units must not assert claim authority")
    if classification == "factual":
        allowed = {fact.value for claim in selected for fact in claim.scope.numeric_facts}
        allowed.update(period for claim in selected for period in claim.scope.periods)
        for token in _NUMBER.findall(text):
            normalized = token.rstrip("%").replace(",", ".")
            if token not in allowed and normalized not in allowed:
                raise ClaimRenderingError(f"numeric prose is not represented by referenced claims: {token}")
    return {"text": text, "claim_ids": list(claim_ids), "classification": classification}


def _claims(ids: tuple[str, ...], claims_by_id: dict[str, ReportClaim]) -> tuple[ReportClaim, ...]:
    if any(item not in claims_by_id for item in ids):
        raise ClaimRenderingError("unknown ReportClaim reference")
    return tuple(claims_by_id[item] for item in ids)


def _ids(value: Any, *, field: str, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ClaimRenderingError(f"{field} must be an array")
    result = tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if required and not result:
        raise ClaimRenderingError(f"{field} must not be empty")
    return result


def _require_array(payload: dict[str, Any], field: str) -> list[Any]:
    if not isinstance(payload, dict) or set(payload) != {field} or not isinstance(payload[field], list):
        raise ClaimRenderingError(f"{field} payload is malformed")
    return payload[field]
