from __future__ import annotations

from application.report.coverage_contract import ReportCoverageContract
from domain.reports.report_claim import ReportClaim
from domain.reports.report_section import ReportSection


def validate_claim_backed_coverage(*, claims: tuple[ReportClaim, ...],
                                   sections: tuple[ReportSection, ...],
                                   contract: ReportCoverageContract,
                                   mandatory_rq_findings: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    claims_by_id = {item.claim_id: item for item in claims}
    errors: list[str] = []
    for rq_id in contract.required_rq_ids:
        eligible = [claim for claim in claims if rq_id in claim.research_question_ids and (not mandatory_rq_findings.get(rq_id) or set(claim.finding_ids) & set(mandatory_rq_findings[rq_id]))]
        if not eligible:
            errors.append(f"claim_coverage_missing:{rq_id}")
            continue
        eligible_ids = {item.claim_id for item in eligible}
        if not any(rq_id in section.research_question_refs and set(section.claim_refs) & eligible_ids for section in sections):
            errors.append(f"claim_section_binding_missing:{rq_id}")
    for rq_id in contract.excluded_rq_ids:
        if any(rq_id in claim.research_question_ids for claim in claims):
            errors.append(f"excluded_rq_claimed_complete:{rq_id}")
    for section in sections:
        if not section.claim_refs:
            errors.append(f"substantive_section_claim_missing:{section.id}")
        if any(ref not in claims_by_id for ref in section.claim_refs):
            errors.append(f"unknown_section_claim_ref:{section.id}")
    return tuple(errors)
