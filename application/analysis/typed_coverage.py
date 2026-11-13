"""Validate classified Finding authority without executing providers."""
from application.analysis.derivations import dependency_authority, validate_deterministic_derivation
from application.ports.analysis_ports import FindingCandidate
from domain.planning.derivation import InformationNeedKind as Kind


def supports_need(finding,need,*,project_id,design,findings,evidence_by_id,brief,source_repository,visiting=()):
    if finding.id in visiting or finding.project_id!=project_id or finding.research_design_id!=design.id or finding.metadata.get("validation_status")!="validated" or need.id not in finding.information_need_refs or not finding.evidence_refs:
        return False
    if any(eid not in evidence_by_id for eid in finding.evidence_refs):
        return False
    if need.kind==Kind.ACQUIRED:
        return any(need.id in evidence_by_id[eid].information_need_refs for eid in finding.evidence_refs)
    if need.kind!=Kind.DERIVED or tuple(finding.information_need_refs)!=(need.id,):
        return False
    proof=finding.metadata.get("derivation")
    if not isinstance(proof,dict) or proof.get("validation_status")!="validated" or proof.get("contract")!=need.derivation.to_dict() or proof.get("operation_type")!=need.derivation.operation_type.value:
        return False
    try:
        deps=[findings[fid] for fid in proof["dependency_finding_ids"]]
        if not deps or len(deps)>need.derivation.max_inputs or set(proof["input_evidence_ids"])!=set(finding.evidence_refs):
            return False
        need_by_id={n.id:n for n in design.information_needs}
        for ref in need.depends_on_information_need_ids:
            if not any(supports_need(dep,need_by_id[ref],project_id=project_id,design=design,findings=findings,
                evidence_by_id=evidence_by_id,brief=brief,source_repository=source_repository,visiting=(*visiting,finding.id)) for dep in deps):
                return False
        scope=dict(design=design,project_id=project_id,workflow_run_id=finding.workflow_run_id,
            allowed_runs=tuple({e.workflow_run_id for e in evidence_by_id.values()}),source_repository=source_repository)
        checked_deps,inputs=dependency_authority(need,deps,tuple(evidence_by_id.values()),brief=brief,**scope)
        if {f.id for f in checked_deps}!=set(proof["dependency_finding_ids"]) or {e.id for e in inputs}!=set(finding.evidence_refs):
            return False
        if need.derivation.operation_type.deterministic:
            current_inputs={e.id for e in evidence_by_id.values() if e.metadata.get("structured_table")
                and e.metadata.get("observation_period") in need.derivation.required_periods
                and set(e.information_need_refs).intersection(need.depends_on_information_need_ids)}
            if not current_inputs<=set(finding.evidence_refs):
                return False
            candidate=FindingCandidate(finding.statement,finding.rationale,finding.evidence_refs,
                finding.research_question_refs,finding.information_need_refs,finding.finding_type.value,
                finding.confidence,{k:v for k,v in finding.metadata.items() if k!="validation_status"})
            validate_deterministic_derivation(candidate,need,inputs,checked_deps,brief=brief,**scope)
            return True
        if proof.get("validation_method")!="semantic-entailment-v1":
            return False
        lineage=proof.get("source_revision_lineage",[])
        if {row.get("evidence_id") for row in lineage}!=set(finding.evidence_refs):
            return False
        for row in lineage:
            evidence=evidence_by_id[row["evidence_id"]]
            source=source_repository.get_by_id(evidence.source_id)
            if row.get("source_id")!=source.id or row.get("source_content_checksum")!=source.content_checksum or row.get("content_revision")!=source.content_revision or row.get("extraction_revision")!=source.extraction_revision:
                return False
        return True
    except (ValueError,ArithmeticError,KeyError,TypeError,AttributeError):
        return False
