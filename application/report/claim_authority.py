from __future__ import annotations

from dataclasses import dataclass

from application.report.claim_contract import authority_digest, content_digest, scope_from_authoritative_payload
from application.research_scope.authoritative_scope import SCOPE_KEY, combine_evidence_scopes, scope_for_finding
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign
from domain.reports.report_claim import ClaimScope


class ClaimAuthorityError(ValueError):
    pass


@dataclass(frozen=True)
class ClaimAuthority:
    project_id: str
    source_workflow_run_id: str
    report_workflow_run_id: str
    design_id: str
    research_question_ids: tuple[str, ...]
    information_need_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    scope: ClaimScope
    finding_content_digests: dict[str, str]
    evidence_content_digests: dict[str, str]
    authority_digest: str


def derive_claim_authority(*, project_id: str, source_workflow_run_id: str, report_workflow_run_id: str, design: ResearchDesign, findings: tuple[Finding, ...], evidence_by_id: dict[str, Evidence]) -> ClaimAuthority:
    if not findings:
        raise ClaimAuthorityError("at least one validated Finding is required")
    allowed_rqs = {item.id for item in design.research_questions}
    allowed_needs = {item.id for item in design.information_needs}
    finding_ids, evidence_ids, rq_ids, need_ids = set(), set(), set(), set()
    for finding in findings:
        if finding.project_id != project_id or finding.workflow_run_id != source_workflow_run_id or finding.research_design_id != design.id:
            raise ClaimAuthorityError("Finding lineage is foreign")
        finding_ids.add(finding.id); rq_ids.update(finding.research_question_refs); need_ids.update(finding.information_need_refs)
        evidence_ids.update(finding.evidence_refs)
    if not rq_ids or not need_ids or not rq_ids <= allowed_rqs or not need_ids <= allowed_needs:
        raise ClaimAuthorityError("Finding RQ/IN lineage is invalid")
    evidence = []
    for evidence_id in sorted(evidence_ids):
        item = evidence_by_id.get(evidence_id)
        if item is None or item.project_id != project_id or item.workflow_run_id != source_workflow_run_id or item.research_design_id != design.id:
            raise ClaimAuthorityError("Evidence lineage is foreign or unreachable")
        if not set(item.research_question_refs) <= rq_ids or not set(item.information_need_refs) <= need_ids:
            raise ClaimAuthorityError("Evidence is outside Finding RQ/IN reachability")
        evidence.append(item)
    # Scope is combined only from the selected Findings' cited authoritative Evidence.
    scope_payload = combine_evidence_scopes(evidence)
    raw_scales: dict[tuple[str, str], str] = {}
    for item in evidence:
        raw_scope = item.metadata.get(SCOPE_KEY)
        if not isinstance(raw_scope, dict):
            continue
        for fact in raw_scope.get("numeric_facts", []):
            if isinstance(fact, dict) and fact.get("value") is not None and fact.get("unit") is not None:
                raw_scales[(str(fact["value"]).casefold(), str(fact["unit"]).casefold())] = str(fact.get("scale") or "absolute")
    scope_payload["numeric_facts"] = [
        {**fact, "scale": raw_scales.get((str(fact.get("value", "")).casefold(), str(fact.get("unit", "")).casefold()), "absolute")}
        for fact in scope_payload["numeric_facts"]
    ]
    scope = scope_from_authoritative_payload(scope_payload)
    finding_digests = {item.id: content_digest({"statement": item.statement, "rationale": item.rationale, "evidence_refs": sorted(item.evidence_refs), "scope": scope_for_finding(item, evidence_by_id)}) for item in findings}
    evidence_digests = {item.id: content_digest({"statement": item.statement, "source_excerpt": item.source_excerpt, "source_id": item.source_id, "source_content_checksum": item.source_content_checksum}) for item in evidence}
    digest = authority_digest(source_workflow_run_id=source_workflow_run_id, design_id=design.id, finding_content_digests=finding_digests, evidence_content_digests=evidence_digests, scope=scope)
    return ClaimAuthority(project_id, source_workflow_run_id, report_workflow_run_id, design.id, tuple(sorted(rq_ids)), tuple(sorted(need_ids)), tuple(sorted(finding_ids)), tuple(sorted(evidence_ids)), tuple(sorted({item.source_id for item in evidence})), scope, finding_digests, evidence_digests, digest)
