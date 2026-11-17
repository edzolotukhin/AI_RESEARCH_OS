"""Inactive atomic orchestration for ReportClaim v2 successor creation."""
from __future__ import annotations

from typing import Any

from application.report.claim_lineage_verification_v2 import (
    VerifiedClaimLineageV2Snapshot,
    verify_persisted_claim_v2_snapshot_write_transaction,
)
from application.report.claim_revision_v2 import rebuild_report_claim_v2
from domain.reports.report import Report


def create_report_claim_v2_successor(
    *,
    session_factory: Any,
    parent_report_id: str,
    parent_claim_id: str,
    successor_report: Any,
    validated_at: str,
    report_repository: Any,
    report_claim_repository: Any,
    finding_repository: Any,
    insight_repository: Any,
    evidence_repository: Any,
    source_repository: Any,
    workflow_run_repository: Any,
    workflow_template_repository: Any,
) -> tuple[Any, Any, VerifiedClaimLineageV2Snapshot]:
    """Atomically create one v2 Report/Claim successor.

    The caller supplies the complete successor Report domain object. This seam
    is intentionally inactive until an application route explicitly invokes it.
    """
    if not isinstance(successor_report, Report):
        raise TypeError("successor_report must be a Report")
    with session_factory.repeatable_read_transaction():
        parent = report_repository.lock_revision(
            parent_report_id,
            expected_revision=successor_report.revision_number - 1,
        )
        if (
            successor_report.id == parent.id
            or successor_report.previous_report_id != parent.id
            or successor_report.revision_number != parent.revision_number + 1
            or successor_report.project_id != parent.project_id
            or successor_report.workflow_run_id != parent.workflow_run_id
            or successor_report.research_design_id != parent.research_design_id
        ):
            raise ValueError("successor parent identity mismatch")
        snapshot = verify_persisted_claim_v2_snapshot_write_transaction(
            session_factory=session_factory,
            report_id=parent.id,
            claim_id=parent_claim_id,
            report_repository=report_repository,
            report_claim_repository=report_claim_repository,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            workflow_run_repository=workflow_run_repository,
            workflow_template_repository=workflow_template_repository,
        )
        verified_input, context = snapshot.to_revision_inputs()
        successor_claim = rebuild_report_claim_v2(
            verified_input,
            new_report_id=successor_report.id,
            new_report_revision=successor_report.revision_number,
            report_workflow_run_id=successor_report.workflow_run_id,
            validated_at=validated_at,
            context=context,
        )
        report_repository.allocate_successor(
            parent.id,
            expected_revision=parent.revision_number,
            successor=successor_report,
        )
        report_claim_repository.create_with_report(successor_report, (successor_claim,))
        return successor_report, successor_claim, snapshot
