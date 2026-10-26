from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError, derive_claim_authority
from application.report.claim_validation import validate_report_claim
from application.report.claim_rendering import ClaimRenderingError, validate_claim_proposition
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import REPORT_CLAIM_VERSION, ReportClaim

ClaimCandidateProvider = Callable[[dict[str, Any]], dict[str, Any]]


class ClaimGenerationError(ValueError):
    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def generate_validated_claims(
    *, project_id: str, source_workflow_run_id: str,
    report_workflow_run_id: str, design: ResearchDesign,
    findings: tuple[Finding, ...], insights: tuple[Insight, ...],
    evidence_by_id: dict[str, Evidence], citation_id_by_source: dict[str, str],
    candidate_provider: ClaimCandidateProvider | None = None,
    correction_provider: ClaimCandidateProvider | None = None,
) -> tuple[ReportClaim, ...]:
    claims: list[ReportClaim] = []
    for finding in findings:
        authority = derive_claim_authority(
            project_id=project_id,
            source_workflow_run_id=source_workflow_run_id,
            report_workflow_run_id=report_workflow_run_id,
            design=design,
            findings=(finding,),
            evidence_by_id=evidence_by_id,
        )
        envelope = _candidate_payload(
            authority=authority, finding=finding, insights=insights,
            citation_id_by_source=citation_id_by_source,
        )
        raw = candidate_provider(envelope) if candidate_provider else envelope
        try:
            claim = validate_report_claim(ReportClaim.from_dict(raw), authority)
        except (ClaimAuthorityError, ValueError) as first_error:
            if correction_provider is None:
                raise ClaimGenerationError(f"invalid ReportClaim for Finding {finding.id}") from first_error
            corrected_raw = correction_provider({"candidate": raw, "authority": envelope, "errors": [str(first_error)]})
            _validate_narrowing_only(raw, corrected_raw)
            try:
                claim = validate_report_claim(ReportClaim.from_dict(corrected_raw), authority)
            except (ClaimAuthorityError, ValueError) as correction_error:
                raise ClaimGenerationError(f"corrected ReportClaim remains invalid for Finding {finding.id}") from correction_error
        try:
            validate_claim_proposition(claim)
        except ClaimRenderingError as error:
            raise ClaimGenerationError(
                f"ReportClaim proposition exceeds numeric authority for Finding {finding.id}",
                diagnostics=error.diagnostics,
            ) from error
        claims.append(claim)
    return tuple(claims)


def _candidate_payload(*, authority: ClaimAuthority, finding: Finding,
                       insights: tuple[Insight, ...],
                       citation_id_by_source: dict[str, str]) -> dict[str, Any]:
    claim_id = str(uuid5(NAMESPACE_URL, f"{authority.report_workflow_run_id}:{authority.design_id}:{finding.id}:desk_report_claim_v1"))
    kind = {
        FindingType.TREND: "trend", FindingType.COMPARISON: "comparison",
        FindingType.CONTRADICTION: "contradiction",
    }.get(finding.finding_type, "observation")
    certainty = "direct" if finding.confidence is None or finding.confidence >= .75 else "qualified" if finding.confidence >= .5 else "uncertain"
    payload = {
        "version": REPORT_CLAIM_VERSION,
        "claim_id": claim_id,
        "project_id": authority.project_id,
        "source_workflow_run_id": authority.source_workflow_run_id,
        "report_workflow_run_id": authority.report_workflow_run_id,
        "design_id": authority.design_id,
        "research_question_ids": list(authority.research_question_ids),
        "information_need_ids": list(authority.information_need_ids),
        "finding_ids": list(authority.finding_ids),
        "insight_ids": sorted(item.id for item in insights if finding.id in item.finding_refs),
        "evidence_ids": list(authority.evidence_ids),
        "assertion": {"kind": kind, "proposition": finding.statement.strip(), "certainty": certainty, "direction": "not_applicable"},
        "scope": authority.scope.to_dict(),
        "support": {
            "evidence_ids": list(authority.evidence_ids),
            "source_ids": list(authority.source_ids),
            "citation_ids": sorted(citation_id_by_source[source_id] for source_id in authority.source_ids if source_id in citation_id_by_source),
            "finding_content_digests": dict(authority.finding_content_digests),
            "evidence_content_digests": dict(authority.evidence_content_digests),
        },
        "validation": {"status": "validated", "contract_version": REPORT_CLAIM_VERSION, "authority_digest": authority.authority_digest, "validated_at": datetime.now(timezone.utc).isoformat()},
    }
    return payload


def _validate_narrowing_only(original: dict[str, Any], corrected: dict[str, Any]) -> None:
    graph_fields = ("project_id", "source_workflow_run_id", "report_workflow_run_id", "design_id", "research_question_ids", "information_need_ids", "finding_ids", "insight_ids", "evidence_ids")
    for field in graph_fields:
        if corrected.get(field) != original.get(field):
            raise ClaimGenerationError("claim correction may not change lineage or support graph")
    before, after = original.get("scope"), corrected.get("scope")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ClaimGenerationError("claim correction requires structured scope")
    for field in ("periods", "metrics", "population_dimensions"):
        if not set(after.get(field, [])) <= set(before.get(field, [])):
            raise ClaimGenerationError("claim correction may only narrow scope")
    for field in ("country", "subnational"):
        if not set((after.get("geography") or {}).get(field, [])) <= set((before.get("geography") or {}).get(field, [])):
            raise ClaimGenerationError("claim correction may only narrow geography")
    before_facts = {_fact_identity(item) for item in before.get("numeric_facts", []) if isinstance(item, dict)}
    after_facts = {_fact_identity(item) for item in after.get("numeric_facts", []) if isinstance(item, dict)}
    if not after_facts <= before_facts:
        raise ClaimGenerationError("claim correction may not add or alter numeric authority")


def _fact_identity(item: dict[str, Any]) -> str:
    import json
    return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
