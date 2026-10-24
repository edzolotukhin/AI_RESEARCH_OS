from __future__ import annotations

from domain.reports.report_claim import NumericFact, ReportClaim
from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError


def _subset(actual: tuple[str, ...], allowed: tuple[str, ...], label: str) -> None:
    if not set(actual) <= set(allowed):
        raise ClaimAuthorityError(f"unsupported {label}")


def _numeric_supported(candidate: NumericFact, authority: tuple[NumericFact, ...]) -> bool:
    for supported in authority:
        if candidate.value != supported.value or candidate.unit != supported.unit or candidate.scale != supported.scale:
            continue
        if all(set(getattr(candidate, name)) <= set(getattr(supported, name)) for name in ("geography", "periods", "metrics", "population_dimensions")):
            return True
    return False


def validate_report_claim(claim: ReportClaim, authority: ClaimAuthority) -> ReportClaim:
    expected = (authority.project_id, authority.source_workflow_run_id, authority.report_workflow_run_id, authority.design_id)
    actual = (claim.project_id, claim.source_workflow_run_id, claim.report_workflow_run_id, claim.design_id)
    if actual != expected:
        raise ClaimAuthorityError("ReportClaim lineage is foreign")
    for actual_ids, allowed_ids, label in ((claim.research_question_ids, authority.research_question_ids, "ResearchQuestion"), (claim.information_need_ids, authority.information_need_ids, "InformationNeed"), (claim.finding_ids, authority.finding_ids, "Finding"), (claim.evidence_ids, authority.evidence_ids, "Evidence"), (claim.source_ids, authority.source_ids, "Source")):
        _subset(actual_ids, allowed_ids, label)
    if claim.finding_content_digests != {key: authority.finding_content_digests[key] for key in claim.finding_ids}:
        raise ClaimAuthorityError("Finding content digest mismatch")
    if claim.evidence_content_digests != {key: authority.evidence_content_digests[key] for key in claim.evidence_ids}:
        raise ClaimAuthorityError("Evidence content digest mismatch")
    if claim.authority_digest != authority.authority_digest:
        raise ClaimAuthorityError("authority digest mismatch")
    _subset(claim.scope.geography_country, authority.scope.geography_country, "country geography")
    _subset(claim.scope.geography_subnational, authority.scope.geography_subnational, "subnational geography")
    _subset(claim.scope.periods, authority.scope.periods, "period")
    _subset(claim.scope.metrics, authority.scope.metrics, "metric")
    _subset(claim.scope.population_dimensions, authority.scope.population_dimensions, "population dimension")
    if any(not _numeric_supported(item, authority.scope.numeric_facts) for item in claim.scope.numeric_facts):
        raise ClaimAuthorityError("unsupported numeric value/unit/scale or binding")
    return claim
