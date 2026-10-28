"""Durable, source-version-bound PPTX generation state."""

from dataclasses import dataclass
from datetime import datetime

from application.deliverables.approved_delivery_provenance import (
    ApprovedDeliveryProvenance,
    provenance_from_storage,
)


@dataclass(frozen=True)
class PresentationJob:
    id: str
    project_id: str
    method: str
    run_id: str
    study_id: str | None
    source_id: str
    source_version: str
    status_snapshot: str
    template_version: str
    renderer_version: str
    state: str
    attempts: int
    lease_until: datetime | None
    claimed_by: str | None
    created_at: datetime
    updated_at: datetime
    completed_deliverable_id: str | None
    failure_code: str | None
    report_revision: int | None = None
    review_id: str | None = None
    source_run_id: str | None = None
    claim_set_digest: str | None = None
    coverage_contract_digest: str | None = None
    authority_digest: str | None = None
    presentation_digest: str | None = None

    def __post_init__(self) -> None:
        if self.authority_digest is not None or self.presentation_digest is not None:
            self.approved_delivery_provenance

    @property
    def approved_delivery_provenance(self) -> ApprovedDeliveryProvenance | None:
        if self.authority_digest is None and self.presentation_digest is None:
            return None
        return provenance_from_storage(
            report_id=self.source_id,
            revision_number=self.report_revision,
            authority_digest=self.authority_digest,
            presentation_digest=self.presentation_digest,
            review_id=self.review_id,
            source_workflow_run_id=self.source_run_id,
            report_workflow_run_id=self.run_id,
            claim_set_digest=self.claim_set_digest,
            coverage_contract_digest=self.coverage_contract_digest,
        )
