from __future__ import annotations

from uuid import uuid4

from application.report.claim_authority import ClaimAuthorityError, derive_claim_authority
from application.report.claim_coverage import validate_claim_backed_coverage
from application.report.claim_validation import validate_report_claim
from application.report.coverage_contract import ReportCoverageContract
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType


def review_structured_claim_contract(
    *, report: Report, claims: tuple[ReportClaim, ...], design: ResearchDesign,
    findings: list[Finding], insights: list[Insight], evidence_items: list[Evidence],
    source_workflow_run_id: str, coverage_contract: ReportCoverageContract,
) -> tuple[ReviewIssue, ...]:
    """Validate the exact persisted claim graph; prose never establishes authority."""
    errors: list[tuple[str, str | None, tuple[str, ...], tuple[str, ...]]] = []
    claims_by_id = {claim.claim_id: claim for claim in claims}
    findings_by_id = {item.id: item for item in findings}
    insights_by_id = {item.id: item for item in insights}
    evidence_by_id = {item.id: item for item in evidence_items}
    if not claims:
        errors.append(("structured_report_claims_missing", None, (), ()))
    if len(claims_by_id) != len(claims):
        errors.append(("duplicate_report_claim_id", None, (), ()))

    for claim in claims:
        try:
            selected_findings = tuple(findings_by_id[item] for item in claim.finding_ids)
            authority = derive_claim_authority(
                project_id=report.project_id,
                source_workflow_run_id=source_workflow_run_id,
                report_workflow_run_id=report.workflow_run_id,
                design=design,
                findings=selected_findings,
                evidence_by_id=evidence_by_id,
            )
            validate_report_claim(claim, authority)
        except (KeyError, ClaimAuthorityError, ValueError):
            errors.append(("report_claim_authority_invalid", None, (claim.claim_id,), claim.research_question_ids))
            continue
        if any(item not in insights_by_id for item in claim.insight_ids):
            errors.append(("report_claim_insight_unreachable", None, (claim.claim_id,), claim.research_question_ids))
        if any(item not in report.citation_registry for item in claim.citation_ids):
            errors.append(("report_claim_citation_unregistered", None, (claim.claim_id,), claim.research_question_ids))
        else:
            cited_sources = {
                str(report.citation_registry[item].get("source_id", ""))
                for item in claim.citation_ids
                if isinstance(report.citation_registry.get(item), dict)
            }
            if cited_sources != set(claim.source_ids):
                errors.append(("report_claim_citation_derivation_mismatch", None, (claim.claim_id,), claim.research_question_ids))

    for section in report.sections:
        selected = [claims_by_id[item] for item in section.claim_refs if item in claims_by_id]
        if not section.claim_refs or len(selected) != len(section.claim_refs):
            errors.append(("section_claim_ref_invalid", section.id, tuple(section.claim_refs), section.research_question_refs))
            continue
        expected_findings = {item for claim in selected for item in claim.finding_ids}
        expected_evidence = {item for claim in selected for item in claim.evidence_ids}
        expected_insights = {item for claim in selected for item in claim.insight_ids}
        expected_citations = {item for claim in selected for item in claim.citation_ids}
        expected_rqs = {item for claim in selected for item in claim.research_question_ids}
        if set(section.finding_refs) != expected_findings or set(section.evidence_refs) != expected_evidence or set(section.insight_refs) != expected_insights:
            errors.append(("section_claim_provenance_mismatch", section.id, tuple(section.claim_refs), section.research_question_refs))
        if set(section.citation_ids) != expected_citations:
            errors.append(("section_claim_citation_mismatch", section.id, tuple(section.claim_refs), section.research_question_refs))
        if not set(section.research_question_refs) <= expected_rqs:
            errors.append(("section_claim_rq_mismatch", section.id, tuple(section.claim_refs), section.research_question_refs))

    summary_units = report.metadata.get("summary_units")
    if not isinstance(summary_units, list) or not summary_units:
        errors.append(("summary_units_missing", None, (), ()))
    else:
        for unit in summary_units:
            if not isinstance(unit, dict) or set(unit) != {"text", "claim_ids", "classification"}:
                errors.append(("summary_unit_malformed", None, (), ()))
                continue
            refs = tuple(str(item) for item in unit.get("claim_ids", [])) if isinstance(unit.get("claim_ids"), list) else ()
            if unit.get("classification") == "factual" and (not refs or any(item not in claims_by_id for item in refs)):
                errors.append(("summary_claim_ref_invalid", None, refs, ()))
            if unit.get("classification") == "non_factual" and refs:
                errors.append(("summary_nonfactual_claim_ref", None, refs, ()))

    mandatory = {
        rq: tuple(sorted(item.id for item in findings if rq in item.research_question_refs))
        for rq in coverage_contract.required_rq_ids
    }
    for code in validate_claim_backed_coverage(
        claims=claims, sections=report.sections, contract=coverage_contract,
        mandatory_rq_findings=mandatory,
    ):
        rq = (code.split(":", 1)[1],) if ":" in code else ()
        errors.append((code, None, (), rq))

    return tuple(
        ReviewIssue(
            id=str(uuid4()),
            issue_type=ReviewIssueType.STRUCTURE_ISSUE,
            severity=ReviewIssueSeverity.MAJOR,
            message=f"Structured Report claim contract: {code}",
            report_section_id=section_id,
            claim_refs=claim_refs,
            report_revision=report.revision_number,
            research_question_refs=rq_refs,
            suggested_action="Reject corrupted claim authority",
            metadata={"code": code, "non_repairable": True, "structured_claim_contract": "desk_report_claim_v1"},
        )
        for code, section_id, claim_refs, rq_refs in errors
    )
