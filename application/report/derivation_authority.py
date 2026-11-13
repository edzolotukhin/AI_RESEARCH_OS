"""Bridge reproducible Analysis results into H3; no provider-created authority."""
from application.analysis.typed_coverage import supports_need
from application.evidence.temporal_scope import qualifying_evidence
from application.report.claim_authority import ClaimAuthority, ClaimAuthorityError
from application.report.claim_contract import authority_digest, content_digest, scope_from_authoritative_payload
from application.research_scope.authoritative_scope import combine_evidence_scopes
from domain.planning.derivation import InformationNeedKind


def derived_claim_authority(*, finding, findings, evidence_by_id, design, project_id,
                            source_workflow_run_id, report_workflow_run_id, source_repository, brief=None):
    needs = [n for n in design.information_needs if n.id in finding.information_need_refs]
    if len(needs) != 1 or needs[0].kind != InformationNeedKind.DERIVED or source_repository is None:
        raise ClaimAuthorityError("Explicit derived authority is unavailable")
    need = needs[0]
    if finding.workflow_run_id != source_workflow_run_id:
        raise ClaimAuthorityError("Foreign derived workflow")
    evidence_by_id = {e.id: e for e in qualifying_evidence(design=design, evidence=tuple(evidence_by_id.values()),
        brief=brief, source_repository=source_repository) if e.project_id == project_id and e.workflow_run_id == source_workflow_run_id}
    if not supports_need(finding, need, project_id=project_id, design=design, findings={f.id: f for f in findings},
        evidence_by_id=evidence_by_id, brief=brief, source_repository=source_repository):
        raise ClaimAuthorityError("Derived authority failed reproducibility or provenance")
    proof = finding.metadata["derivation"]
    evidence = tuple(evidence_by_id[eid] for eid in finding.evidence_refs)
    payload = combine_evidence_scopes(evidence)
    if need.derivation.operation_type.deterministic:
        # This number is validated by deterministic recomputation above. It is
        # explicitly a calculated result, never disguised as an input Evidence.
        payload["numeric_facts"].insert(0, dict(value=proof["rounded_result"], unit=proof["unit"], scale="absolute",
            periods=[proof["parameters"]["from_period"], proof["parameters"]["to_period"]],
            geography=[proof["geography"]], metrics=[proof["metric"]], population_dimensions=[]))
    scope = scope_from_authoritative_payload(payload)
    finding_digests = {finding.id: content_digest({"statement": finding.statement, "rationale": finding.rationale,
        "evidence_refs": sorted(finding.evidence_refs), "scope": payload, "validated_derivation": proof})}
    evidence_digests = {e.id: content_digest({"statement": e.statement, "source_excerpt": e.source_excerpt,
        "source_id": e.source_id, "source_content_checksum": e.source_content_checksum}) for e in evidence}
    digest = authority_digest(source_workflow_run_id=source_workflow_run_id, design_id=design.id,
        finding_content_digests=finding_digests, evidence_content_digests=evidence_digests, scope=scope)
    return ClaimAuthority(project_id, source_workflow_run_id, report_workflow_run_id, design.id,
        tuple(finding.research_question_refs), (need.id,), (finding.id,), tuple(sorted(finding.evidence_refs)),
        tuple(sorted({e.source_id for e in evidence})), scope, finding_digests, evidence_digests, digest,
        parent_source_workflow_run_id=source_workflow_run_id)
