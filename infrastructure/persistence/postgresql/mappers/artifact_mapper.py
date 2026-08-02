from __future__ import annotations

from application.persistence.records import ArtifactRecord
from infrastructure.persistence.postgresql.models.artifact_model import ArtifactModel


def artifact_to_model(record: ArtifactRecord, *, version: int) -> ArtifactModel:
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
    )


def artifact_to_update_values(record: ArtifactRecord) -> dict:
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
    }


def artifact_from_model(model: ArtifactModel) -> ArtifactRecord:
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
    )
