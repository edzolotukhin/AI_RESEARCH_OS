from __future__ import annotations

from typing import Any, Mapping

from application.report.claim_contract import canonical_digest
from application.report.editorial_contract import (
    EDITORIAL_CONTRACT_VERSION,
    CoverageLimitation,
    CoverageStatus,
    EditorialContractError,
    EvidenceRequirementLabel,
    ImpactLabel,
    MissingDimension,
    PresentationCitation,
    PresentationExecutiveSummary,
    PresentationParagraph,
    PresentationReport,
    PresentationSection,
)
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim


REPORT_CONTRACT_KEY = "report_contract_version"
EDITORIAL_ENVELOPE_KEY = "editorial"
_DIAGNOSTIC_LIST_FIELDS = (
    "selected_claim_refs",
    "selected_fact_refs",
    "selected_period_refs",
    "selected_group_refs",
    "selected_interpretation_refs",
    "selected_limitation_refs",
    "resolved_citation_refs",
)


class PresentationPersistenceError(ValueError):
    pass


def report_claims_authority_digest(claims: tuple[ReportClaim, ...]) -> str:
    if not claims:
        raise PresentationPersistenceError("validated ReportClaims are required")
    payload = [_claim_authority_payload(claim) for claim in claims]
    payload.sort(key=lambda item: item["claim_id"])
    return canonical_digest({"contract_version": EDITORIAL_CONTRACT_VERSION, "claims": payload})


def presentation_report_digest(report: PresentationReport) -> str:
    return canonical_digest(presentation_report_to_dict(report))


def build_editorial_envelope(
    *, presentation: PresentationReport, claims: tuple[ReportClaim, ...],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    authority_digest = report_claims_authority_digest(claims)
    if presentation.authority_digest != authority_digest:
        raise PresentationPersistenceError("presentation authority digest mismatch")
    return {
        "contract_version": EDITORIAL_CONTRACT_VERSION,
        "presentation_report": presentation_report_to_dict(presentation),
        "authority_digest": authority_digest,
        "presentation_digest": presentation_report_digest(presentation),
        "diagnostics": _bounded_diagnostics(diagnostics),
    }


def attach_editorial_envelope(
    metadata: Mapping[str, Any], *, presentation: PresentationReport,
    claims: tuple[ReportClaim, ...], diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(metadata)
    result[REPORT_CONTRACT_KEY] = EDITORIAL_CONTRACT_VERSION
    result[EDITORIAL_ENVELOPE_KEY] = build_editorial_envelope(
        presentation=presentation, claims=claims, diagnostics=diagnostics,
    )
    return result


def read_presentation_report(
    report: Report, *, claims: tuple[ReportClaim, ...] | None = None,
) -> PresentationReport | None:
    version = report.metadata.get(REPORT_CONTRACT_KEY)
    if version is None:
        return None
    if version != EDITORIAL_CONTRACT_VERSION:
        raise PresentationPersistenceError("unsupported report contract version")
    envelope = report.metadata.get(EDITORIAL_ENVELOPE_KEY)
    _exact_object(
        envelope,
        {"contract_version", "presentation_report", "authority_digest", "presentation_digest", "diagnostics"},
        "editorial envelope",
    )
    if envelope["contract_version"] != EDITORIAL_CONTRACT_VERSION:
        raise PresentationPersistenceError("malformed editorial contract version")
    if claims is None:
        raise PresentationPersistenceError("ReportClaims are required to validate editorial authority")
    presentation = presentation_report_from_dict(envelope["presentation_report"])
    expected_source_report_id = report.previous_report_id or report.id
    if presentation.report_id != report.id:
        raise PresentationPersistenceError("presentation Report ID mismatch")
    if presentation.revision_number != report.revision_number:
        raise PresentationPersistenceError("presentation revision mismatch")
    if presentation.source_report_id != expected_source_report_id:
        raise PresentationPersistenceError("presentation source Report ID mismatch")
    if presentation.title != report.title:
        raise PresentationPersistenceError("presentation system title mismatch")
    authority_digest = report_claims_authority_digest(claims)
    if envelope["authority_digest"] != authority_digest or presentation.authority_digest != authority_digest:
        raise PresentationPersistenceError("editorial authority digest mismatch")
    if envelope["presentation_digest"] != presentation_report_digest(presentation):
        raise PresentationPersistenceError("presentation digest mismatch")
    _validate_diagnostics(envelope["diagnostics"], authority_digest, envelope["presentation_digest"])
    return presentation


def presentation_report_to_dict(report: PresentationReport) -> dict[str, Any]:
    return {
        "contract_version": report.contract_version,
        "report_id": report.report_id,
        "revision_number": report.revision_number,
        "source_report_id": report.source_report_id,
        "authority_digest": report.authority_digest,
        "title": report.title,
        "executive_summary": _summary_to_dict(report.executive_summary),
        "sections": [_section_to_dict(item) for item in report.sections],
        "limitations": [_limitation_to_dict(item) for item in report.limitations],
        "citations": [_citation_to_dict(item) for item in report.citations],
    }


def presentation_report_from_dict(payload: Any) -> PresentationReport:
    _exact_object(
        payload,
        {"contract_version", "report_id", "revision_number", "source_report_id", "authority_digest", "title", "executive_summary", "sections", "limitations", "citations"},
        "PresentationReport",
    )
    if payload["contract_version"] != EDITORIAL_CONTRACT_VERSION:
        raise PresentationPersistenceError("unsupported PresentationReport contract version")
    try:
        return PresentationReport(
            contract_version=str(payload["contract_version"]),
            report_id=str(payload["report_id"]),
            revision_number=int(payload["revision_number"]),
            source_report_id=str(payload["source_report_id"]),
            authority_digest=str(payload["authority_digest"]),
            title=str(payload["title"]),
            executive_summary=_summary_from_dict(payload["executive_summary"]),
            sections=tuple(_section_from_dict(item) for item in _array(payload["sections"], "sections")),
            limitations=tuple(_limitation_from_dict(item) for item in _array(payload["limitations"], "limitations")),
            citations=tuple(_citation_from_dict(item) for item in _array(payload["citations"], "citations")),
        )
    except (EditorialContractError, TypeError, ValueError, KeyError) as exc:
        raise PresentationPersistenceError("malformed PresentationReport payload") from exc


def _claim_authority_payload(claim: ReportClaim) -> dict[str, Any]:
    scope = {
        "geography": {
            "country": sorted(claim.scope.geography_country),
            "subnational": sorted(claim.scope.geography_subnational),
        },
        "periods": sorted(claim.scope.periods),
        "metrics": sorted(claim.scope.metrics),
        "population_dimensions": sorted(claim.scope.population_dimensions),
        "numeric_facts": sorted(
            (
                {
                    "value": fact.value,
                    "unit": fact.unit,
                    "scale": fact.scale,
                    "geography": sorted(fact.geography),
                    "periods": sorted(fact.periods),
                    "metrics": sorted(fact.metrics),
                    "population_dimensions": sorted(fact.population_dimensions),
                }
                for fact in claim.scope.numeric_facts
            ),
            key=lambda item: canonical_digest(item),
        ),
    }
    return {
        "claim_id": claim.claim_id,
        "project_id": claim.project_id,
        "source_workflow_run_id": claim.source_workflow_run_id,
        "report_workflow_run_id": claim.report_workflow_run_id,
        "design_id": claim.design_id,
        "research_question_ids": sorted(claim.research_question_ids),
        "information_need_ids": sorted(claim.information_need_ids),
        "finding_ids": sorted(claim.finding_ids),
        "insight_ids": sorted(claim.insight_ids),
        "evidence_ids": sorted(claim.evidence_ids),
        "kind": claim.kind,
        "certainty": claim.certainty,
        "direction": claim.direction,
        "scope": scope,
        "support_evidence_ids": sorted(claim.support_evidence_ids),
        "source_ids": sorted(claim.source_ids),
        "citation_ids": sorted(claim.citation_ids),
        "finding_content_digests": dict(sorted(claim.finding_content_digests.items())),
        "evidence_content_digests": dict(sorted(claim.evidence_content_digests.items())),
        "claim_authority_digest": claim.authority_digest,
    }


def _bounded_diagnostics(value: Mapping[str, Any]) -> dict[str, Any]:
    attempts = value.get("attempts", [])
    if not isinstance(attempts, list):
        attempts = []
    bounded_attempts = []
    for item in attempts[:2]:
        if not isinstance(item, Mapping):
            continue
        codes = item.get("validation_codes", [])
        bounded_attempts.append({
            "attempt": str(item.get("attempt", ""))[:16],
            "status": str(item.get("status", ""))[:16],
            "validation_codes": [str(code)[:64] for code in codes[:16]] if isinstance(codes, list) else [],
        })
    result: dict[str, Any] = {
        "contract_version": EDITORIAL_CONTRACT_VERSION,
        "provider_call_count": int(value.get("provider_call_count", 0)),
        "stage": str(value.get("stage", ""))[:64],
        "attempts": bounded_attempts,
    }
    if not 0 <= result["provider_call_count"] <= 2:
        raise PresentationPersistenceError("editorial provider call bound exceeded")
    for field in _DIAGNOSTIC_LIST_FIELDS:
        items = value.get(field, [])
        result[field] = [str(item)[:128] for item in items[:64]] if isinstance(items, list) else []
    result["authority_digest"] = str(value.get("authority_digest", ""))
    result["presentation_digest"] = str(value.get("presentation_digest", ""))
    return result


def _validate_diagnostics(value: Any, authority_digest: str, presentation_digest: str) -> None:
    fields = {"contract_version", "provider_call_count", "stage", "attempts", "authority_digest", "presentation_digest", *_DIAGNOSTIC_LIST_FIELDS}
    _exact_object(value, fields, "editorial diagnostics")
    if value["contract_version"] != EDITORIAL_CONTRACT_VERSION:
        raise PresentationPersistenceError("editorial diagnostics contract mismatch")
    if not isinstance(value["provider_call_count"], int) or not 0 <= value["provider_call_count"] <= 2:
        raise PresentationPersistenceError("editorial diagnostics provider call count invalid")
    if value["authority_digest"] != authority_digest or value["presentation_digest"] != presentation_digest:
        raise PresentationPersistenceError("editorial diagnostics digest mismatch")
    if not isinstance(value["stage"], str) or not isinstance(value["attempts"], list) or len(value["attempts"]) > 2:
        raise PresentationPersistenceError("editorial diagnostics stage/attempts invalid")
    for attempt in value["attempts"]:
        _exact_object(attempt, {"attempt", "status", "validation_codes"}, "editorial diagnostic attempt")
        if not isinstance(attempt["attempt"], str) or not isinstance(attempt["status"], str):
            raise PresentationPersistenceError("editorial diagnostic attempt invalid")
        _strings(attempt["validation_codes"], "validation_codes")
    for field in _DIAGNOSTIC_LIST_FIELDS:
        _strings(value[field], field)


def _paragraph_to_dict(item: PresentationParagraph) -> dict[str, Any]:
    return {"paragraph_id": item.paragraph_id, "text": item.text, "unit_ids": list(item.unit_ids), "claim_refs": list(item.claim_refs), "fact_refs": list(item.fact_refs), "period_refs": list(item.period_refs), "citation_refs": list(item.citation_refs), "limitation_refs": list(item.limitation_refs)}


def _paragraph_from_dict(payload: Any) -> PresentationParagraph:
    fields = {"paragraph_id", "text", "unit_ids", "claim_refs", "fact_refs", "period_refs", "citation_refs", "limitation_refs"}
    _exact_object(payload, fields, "PresentationParagraph")
    return PresentationParagraph(str(payload["paragraph_id"]), str(payload["text"]), _strings(payload["unit_ids"], "unit_ids"), _strings(payload["claim_refs"], "claim_refs"), _strings(payload["fact_refs"], "fact_refs"), _strings(payload["period_refs"], "period_refs"), _strings(payload["citation_refs"], "citation_refs"), _strings(payload["limitation_refs"], "limitation_refs"))


def _summary_to_dict(item: PresentationExecutiveSummary) -> dict[str, Any]:
    return {"unit_ids": list(item.unit_ids), "paragraphs": [_paragraph_to_dict(value) for value in item.paragraphs]}


def _summary_from_dict(payload: Any) -> PresentationExecutiveSummary:
    _exact_object(payload, {"unit_ids", "paragraphs"}, "PresentationExecutiveSummary")
    return PresentationExecutiveSummary(_strings(payload["unit_ids"], "unit_ids"), tuple(_paragraph_from_dict(item) for item in _array(payload["paragraphs"], "paragraphs")))


def _section_to_dict(item: PresentationSection) -> dict[str, Any]:
    return {"section_id": item.section_id, "title": item.title, "unit_ids": list(item.unit_ids), "paragraphs": [_paragraph_to_dict(value) for value in item.paragraphs]}


def _section_from_dict(payload: Any) -> PresentationSection:
    _exact_object(payload, {"section_id", "title", "unit_ids", "paragraphs"}, "PresentationSection")
    return PresentationSection(str(payload["section_id"]), str(payload["title"]), _strings(payload["unit_ids"], "unit_ids"), tuple(_paragraph_from_dict(item) for item in _array(payload["paragraphs"], "paragraphs")))


def _limitation_to_dict(item: CoverageLimitation) -> dict[str, Any]:
    return {"limitation_id": item.limitation_id, "topic_ref": item.topic_ref, "supported_claim_refs": list(item.supported_claim_refs), "supported_period_refs": list(item.supported_period_refs), "missing_dimensions": [value.value for value in item.missing_dimensions], "missing_periods": list(item.missing_periods), "coverage_status": item.coverage_status.value, "impact_label": item.impact_label.value, "evidence_requirement_labels": [value.value for value in item.evidence_requirement_labels]}


def _limitation_from_dict(payload: Any) -> CoverageLimitation:
    fields = {"limitation_id", "topic_ref", "supported_claim_refs", "supported_period_refs", "missing_dimensions", "missing_periods", "coverage_status", "impact_label", "evidence_requirement_labels"}
    _exact_object(payload, fields, "CoverageLimitation")
    return CoverageLimitation(str(payload["limitation_id"]), str(payload["topic_ref"]), _strings(payload["supported_claim_refs"], "supported_claim_refs"), _strings(payload["supported_period_refs"], "supported_period_refs"), tuple(MissingDimension(item) for item in _strings(payload["missing_dimensions"], "missing_dimensions")), _strings(payload["missing_periods"], "missing_periods"), CoverageStatus(payload["coverage_status"]), ImpactLabel(payload["impact_label"]), tuple(EvidenceRequirementLabel(item) for item in _strings(payload["evidence_requirement_labels"], "evidence_requirement_labels")))


def _citation_to_dict(item: PresentationCitation) -> dict[str, Any]:
    return {"citation_ref": item.citation_ref, "claim_ref": item.claim_ref, "citation_id": item.citation_id, "source_id": item.source_id, "title": item.title, "canonical_url": item.canonical_url, "display_key": item.display_key}


def _citation_from_dict(payload: Any) -> PresentationCitation:
    fields = {"citation_ref", "claim_ref", "citation_id", "source_id", "title", "canonical_url", "display_key"}
    _exact_object(payload, fields, "PresentationCitation")
    return PresentationCitation(*(str(payload[field]) for field in ("citation_ref", "claim_ref", "citation_id", "source_id", "title", "canonical_url", "display_key")))


def _exact_object(value: Any, fields: set[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PresentationPersistenceError(f"{name} fields invalid")


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise PresentationPersistenceError(f"{name} must be an array")
    return value


def _strings(value: Any, name: str) -> tuple[str, ...]:
    items = _array(value, name)
    if any(not isinstance(item, str) or not item for item in items):
        raise PresentationPersistenceError(f"{name} contains invalid values")
    return tuple(items)
