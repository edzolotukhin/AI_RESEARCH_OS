"""Single fail-closed resolver for Desk research product outcomes."""

from __future__ import annotations

from typing import Iterable


def derive_authoritative_outcome(
    *, required_information_need_ids: Iterable[str], readiness_payload: dict | None,
    findings: Iterable, evidence: Iterable, project_id: str, workflow_run_id: str,
    research_design_id: str, technical_failure: bool = False,
    coverage_missing_information_need_ids: Iterable[str] = (),
) -> tuple[str, tuple[str, ...]]:
    required = {str(item) for item in required_information_need_ids if str(item)}
    if technical_failure:
        return "FAILED", tuple(sorted(required))
    if not required or not isinstance(readiness_payload, dict):
        return "INSUFFICIENT", tuple(sorted(required))
    kinds={}
    if readiness_payload.get("classification_version")=="analysis-kind-readiness-v1":
        kinds=readiness_payload.get("information_need_kinds",{})
        if not isinstance(kinds,dict) or not required<=set(kinds) or any(kind not in {"ACQUIRED","DERIVED","OUTPUT"} for kind in kinds.values()):
            return "INSUFFICIENT",tuple(sorted(required))
        required={ref for ref in required if kinds[ref]!="OUTPUT"}
        if not required:
            return "INSUFFICIENT",()
    eligible = {str(item) for item in readiness_payload.get("analysis_eligible_information_need_ids", ())}
    blocking = {str(item) for item in readiness_payload.get("blocking_information_need_ids", ())}
    evidence_by_id = {str(item.id): item for item in evidence}
    findings=tuple(findings)
    findings_by_id={f.id:f for f in findings} if kinds else {}
    resolved: set[str] = set()
    for finding in findings:
        if (finding.project_id, finding.workflow_run_id, finding.research_design_id) != (project_id, workflow_run_id, research_design_id):
            continue
        refs = {str(item) for item in getattr(finding, "information_need_refs", ())}
        if kinds and any(kinds.get(ref)!="ACQUIRED" for ref in refs):
            continue
        evidence_refs = tuple(str(item) for item in getattr(finding, "evidence_refs", ()))
        if not refs or not refs <= required or (eligible and not refs <= eligible) or not evidence_refs:
            continue
        if getattr(finding, "metadata", {}).get("validation_status") != "validated":
            continue
        cited = [evidence_by_id.get(item) for item in evidence_refs]
        if any(item is None for item in cited):
            continue
        if any((item.project_id, item.workflow_run_id, item.research_design_id) != (project_id, workflow_run_id, research_design_id) or not refs.intersection(getattr(item, "information_need_refs", ())) for item in cited):
            continue
        resolved.update(refs)
    if kinds:
        prerequisites=readiness_payload.get("derived_prerequisites",{})
        for _ in range(len(required)):
            before=set(resolved)
            for finding in findings:
                refs=set(finding.information_need_refs)
                if len(refs)!=1:
                    continue
                ref=next(iter(refs))
                if ref not in required or kinds.get(ref)!="DERIVED" or ref not in eligible:
                    continue
                if (finding.project_id,finding.workflow_run_id,finding.research_design_id)!=(project_id,workflow_run_id,research_design_id) or finding.metadata.get("validation_status")!="validated":
                    continue
                proof=finding.metadata.get("derivation",{})
                expected=prerequisites.get(ref,{})
                deps=set(expected.get("dependency_information_need_ids",()))
                if not deps or not deps<=resolved or proof.get("validation_status")!="validated" or proof.get("validation_method") not in {"deterministic-recompute-v1","semantic-entailment-v1"} or proof.get("contract")!=expected.get("contract"):
                    continue
                cited=[evidence_by_id.get(eid) for eid in finding.evidence_refs]
                dep_findings=[findings_by_id.get(fid) for fid in proof.get("dependency_finding_ids",())]
                if not cited or set(proof.get("input_evidence_ids",()))!=set(finding.evidence_refs) or any(e is None or (e.project_id,e.workflow_run_id,e.research_design_id)!=(project_id,workflow_run_id,research_design_id) for e in cited):
                    continue
                if not dep_findings or any(f is None or (f.project_id,f.workflow_run_id,f.research_design_id)!=(project_id,workflow_run_id,research_design_id) or f.metadata.get("validation_status")!="validated" for f in dep_findings):
                    continue
                if not all(any(dep in f.information_need_refs for f in dep_findings) for dep in deps):
                    continue
                resolved.add(ref)
            if before==resolved:
                break
    resolved.difference_update(
        str(item) for item in coverage_missing_information_need_ids
        if str(item) in required
    )
    unresolved = required - resolved
    unresolved.update(blocking - resolved)
    unresolved.update(
        str(item) for item in coverage_missing_information_need_ids
        if str(item) in required
    )
    if not resolved:
        return "INSUFFICIENT", tuple(sorted(unresolved))
    if unresolved:
        return "PARTIAL", tuple(sorted(unresolved))
    return "COMPLETED", ()
