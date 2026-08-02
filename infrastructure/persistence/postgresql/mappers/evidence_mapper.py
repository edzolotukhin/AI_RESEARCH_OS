from __future__ import annotations

from datetime import datetime

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType

from infrastructure.persistence.postgresql.models.evidence_model import EvidenceModel


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evidence_to_model(evidence: Evidence, *, version: int) -> EvidenceModel:
    return EvidenceModel(
        id=evidence.id,
        project_id=evidence.project_id,
        source_id=evidence.source_id,
        source_content_checksum=evidence.source_content_checksum,
        workflow_run_id=evidence.workflow_run_id,
        research_design_id=evidence.research_design_id,
        research_question_refs=list(evidence.research_question_refs),
        information_need_refs=list(evidence.information_need_refs),
        evidence_type=evidence.evidence_type.value,
        statement=evidence.statement,
        source_excerpt=evidence.source_excerpt,
        source_locator=dict(evidence.source_locator),
        extraction_method=evidence.extraction_method,
        confidence=evidence.confidence,
        quality_signals=dict(evidence.quality_signals),
        deduplication_key=evidence.deduplication_key,
        created_at=_parse_datetime(evidence.created_at),
        metadata_json=dict(evidence.metadata),
        version=version,
    )


def evidence_from_model(model: EvidenceModel) -> Evidence:
    return Evidence(
        id=model.id,
        project_id=model.project_id,
        source_id=model.source_id,
        source_content_checksum=model.source_content_checksum,
        workflow_run_id=model.workflow_run_id,
        research_design_id=model.research_design_id,
        research_question_refs=tuple(
            str(item) for item in (model.research_question_refs or [])
        ),
        information_need_refs=tuple(
            str(item) for item in (model.information_need_refs or [])
        ),
        evidence_type=EvidenceType(model.evidence_type),
        statement=model.statement,
        source_excerpt=model.source_excerpt,
        source_locator=dict(model.source_locator or {}),
        extraction_method=model.extraction_method,
        confidence=model.confidence,
        quality_signals=dict(model.quality_signals or {}),
        deduplication_key=model.deduplication_key,
        created_at=model.created_at.isoformat(),
        metadata=dict(model.metadata_json or {}),
        version=model.version,
    )
