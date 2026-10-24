from __future__ import annotations

from datetime import datetime

from domain.reports.report_claim import ReportClaim
from infrastructure.persistence.postgresql.models.report_claim_model import ReportClaimModel


def report_claim_to_model(claim: ReportClaim, *, report_id: str, report_revision: int) -> ReportClaimModel:
    return ReportClaimModel(id=claim.claim_id, report_id=report_id, report_revision=report_revision, project_id=claim.project_id, source_workflow_run_id=claim.source_workflow_run_id, report_workflow_run_id=claim.report_workflow_run_id, research_design_id=claim.design_id, contract_version=claim.contract_version, claim_payload=claim.to_dict(), authority_digest=claim.authority_digest, created_at=datetime.fromisoformat(claim.validated_at.replace("Z", "+00:00")))


def report_claim_from_model(model: ReportClaimModel) -> ReportClaim:
    return ReportClaim.from_dict(dict(model.claim_payload))
