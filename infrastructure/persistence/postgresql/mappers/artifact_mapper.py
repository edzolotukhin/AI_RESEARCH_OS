from __future__ import annotations

from application.persistence.records import ArtifactRecord
from application.deliverables.approved_delivery_provenance import (
    provenance_from_storage,
    validate_storage_binding,
)
from infrastructure.persistence.postgresql.models.artifact_model import ArtifactModel


def artifact_to_model(record: ArtifactRecord, *, version: int) -> ArtifactModel:
    validate_storage_binding(
        record.approved_delivery_provenance,
        report_id=record.report_id,
        report_workflow_run_id=record.run_id,
    )
    provenance = record.approved_delivery_provenance
    return ArtifactModel(
        id=record.id,
        project_id=record.project_id,
        run_id=record.run_id,
        artifact_type=record.artifact_type,
        title=record.title,
        content=record.content,
        status=record.status,
        version=version,
        media_type=record.media_type,
        filename=record.filename,
        content_checksum=record.content_checksum,
        deduplication_key=record.deduplication_key,
        report_id=record.report_id,
        approved_revision_number=provenance.revision_number if provenance else None,
        approved_authority_digest=provenance.authority_digest if provenance else None,
        approved_presentation_digest=provenance.presentation_digest if provenance else None,
        approved_review_id=provenance.review_id if provenance else None,
        approved_source_workflow_run_id=(provenance.source_workflow_run_id if provenance else None),
        approved_claim_set_digest=provenance.claim_set_digest if provenance else None,
        approved_coverage_contract_digest=(provenance.coverage_contract_digest if provenance else None),
    )


def artifact_to_update_values(record: ArtifactRecord) -> dict:
    validate_storage_binding(
        record.approved_delivery_provenance,
        report_id=record.report_id,
        report_workflow_run_id=record.run_id,
    )
    provenance = record.approved_delivery_provenance
    return {
        "project_id": record.project_id,
        "run_id": record.run_id,
        "artifact_type": record.artifact_type,
        "title": record.title,
        "content": record.content,
        "status": record.status,
        "media_type": record.media_type,
        "filename": record.filename,
        "content_checksum": record.content_checksum,
        "deduplication_key": record.deduplication_key,
        "report_id": record.report_id,
        "approved_revision_number": provenance.revision_number if provenance else None,
        "approved_authority_digest": provenance.authority_digest if provenance else None,
        "approved_presentation_digest": provenance.presentation_digest if provenance else None,
        "approved_review_id": provenance.review_id if provenance else None,
        "approved_source_workflow_run_id": (provenance.source_workflow_run_id if provenance else None),
        "approved_claim_set_digest": provenance.claim_set_digest if provenance else None,
        "approved_coverage_contract_digest": (provenance.coverage_contract_digest if provenance else None),
    }


def artifact_from_model(model: ArtifactModel) -> ArtifactRecord:
    provenance = provenance_from_storage(
        report_id=model.report_id,
        revision_number=model.approved_revision_number,
        authority_digest=model.approved_authority_digest,
        presentation_digest=model.approved_presentation_digest,
        review_id=model.approved_review_id,
        source_workflow_run_id=model.approved_source_workflow_run_id,
        report_workflow_run_id=model.run_id,
        claim_set_digest=model.approved_claim_set_digest,
        coverage_contract_digest=model.approved_coverage_contract_digest,
    )
    return ArtifactRecord(
        id=model.id,
        project_id=model.project_id,
        run_id=model.run_id,
        artifact_type=model.artifact_type,
        title=model.title,
        content=model.content,
        status=model.status,
        version=model.version,
        media_type=model.media_type,
        filename=model.filename,
        content_checksum=model.content_checksum,
        deduplication_key=model.deduplication_key,
        report_id=model.report_id,
        approved_delivery_provenance=provenance,
    )
