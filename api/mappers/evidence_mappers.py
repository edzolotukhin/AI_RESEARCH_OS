from __future__ import annotations

from domain.evidence.evidence import Evidence

from api.schemas.evidence import EvidenceResponse


def evidence_to_response(evidence: Evidence) -> EvidenceResponse:
    return EvidenceResponse(
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
        created_at=evidence.created_at,
        metadata=dict(evidence.metadata),
    )
