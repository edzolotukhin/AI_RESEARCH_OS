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
    eligible = {str(item) for item in readiness_payload.get("analysis_eligible_information_need_ids", ())}
    blocking = {str(item) for item in readiness_payload.get("blocking_information_need_ids", ())}
    evidence_by_id = {str(item.id): item for item in evidence}
    resolved: set[str] = set()
    for finding in findings:
        if (finding.project_id, finding.workflow_run_id, finding.research_design_id) != (project_id, workflow_run_id, research_design_id):
            continue
        refs = {str(item) for item in getattr(finding, "information_need_refs", ())}
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
