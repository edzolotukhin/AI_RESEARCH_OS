from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import ReportClaim
from domain.reports.report_section import ReportSection
from application.research_scope.numeric_normalization import (
    RenderedFact,
    rendered_fact_matches_numeric_fact,
    rendered_facts,
)


class ClaimRenderingError(ValueError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True)
class RenderedReport:
    sections: tuple[ReportSection, ...]
    summary_units: tuple[dict[str, Any], ...]
    executive_summary: str


def validate_claim_proposition(claim: ReportClaim) -> None:
    _validate_unit(
        {"text": claim.proposition, "claim_ids": [claim.claim_id], "classification": "factual"},
        {claim.claim_id: claim}, field="claim_proposition",
    )


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
    paragraphs = tuple(_validate_unit(item, claims_by_id, field="paragraph", section=raw) for item in raw["paragraphs"] if isinstance(item, dict)) if isinstance(raw["paragraphs"], list) else ()
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


def _validate_unit(raw: Any, claims_by_id: dict[str, ReportClaim], *, field: str, section: dict[str, Any] | None = None) -> dict[str, Any]:
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
        for rendered in rendered_facts(text):
            if not any(
                rendered_fact_matches_numeric_fact(rendered, fact)[0]
                and _direction_compatible(rendered, claim.direction)
                for claim in selected
                for fact in claim.scope.numeric_facts
            ):
                raise ClaimRenderingError(
                    f"numeric prose is not represented by referenced claims: {rendered.raw}",
                    diagnostics=_numeric_failure_diagnostics(
                        raw=raw, field=field, section=section, selected=selected,
                        rendered=rendered,
                    ),
                )
    return {"text": text, "claim_ids": list(claim_ids), "classification": classification}


def _direction_compatible(rendered: RenderedFact, claim_direction: str) -> bool:
    if rendered.direction is None or claim_direction == "not_applicable":
        return True
    return rendered.direction == claim_direction


def _numeric_failure_diagnostics(*, raw: dict[str, Any], field: str, section: dict[str, Any] | None,
                                 selected: tuple[ReportClaim, ...], rendered: RenderedFact) -> dict[str, Any]:
    """Return bounded structural context; never include full generated prose."""
    text = str(raw.get("text", ""))
    index = text.find(rendered.raw)
    start = max(0, index - 48) if index >= 0 else 0
    end = min(len(text), (index + len(rendered.raw) + 48) if index >= 0 else 96)
    rejected = []
    for claim in selected:
        for fact in claim.scope.numeric_facts:
            _, dimensions = rendered_fact_matches_numeric_fact(rendered, fact)
            rejected.append({
                "claim_id": claim.claim_id[:128],
                "value": fact.value[:64], "unit": fact.unit[:32], "scale": fact.scale[:32],
                "periods": [item[:64] for item in fact.periods][:8],
                "mismatched_dimensions": list(dimensions)[:8],
            })
    return {
        "code": "numeric_prose_unrepresented",
        "unit_type": field,
        "section_id": str(section.get("section_id"))[:128] if section else None,
        "section_title": str(section.get("title"))[:160] if section else None,
        "research_question_ids": [str(item)[:128] for item in (section or {}).get("research_question_ids", [])][:16],
        "rejected_tokens": [(
            f"{rendered.value}%" if rendered.value is not None and rendered.unit == "%"
            else rendered.value or rendered.raw
        )[:64]],
        "rendered_fact": {
            "value": rendered.value, "unit": rendered.unit, "scale": rendered.scale,
            "periods": list(rendered.periods)[:8], "direction": rendered.direction,
        },
        "rejected_numeric_facts": rejected[:16],
        "claim_ids": [claim.claim_id[:128] for claim in selected][:32],
        "finding_ids": [item for claim in selected for item in claim.finding_ids][:32],
        "evidence_ids": [item for claim in selected for item in claim.evidence_ids][:32],
        "allowed_numeric_values": [fact.value[:64] for claim in selected for fact in claim.scope.numeric_facts][:32],
        "allowed_period_values": [period[:64] for claim in selected for period in claim.scope.periods][:32],
        "prose_excerpt": text[start:end][:128],
        "source_workflow_run_ids": sorted({claim.source_workflow_run_id for claim in selected})[:8],
        "report_workflow_run_ids": sorted({claim.report_workflow_run_id for claim in selected})[:8],
    }


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
