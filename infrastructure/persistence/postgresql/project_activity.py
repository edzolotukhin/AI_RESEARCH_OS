"""Minimal Activity insertion; callers own the authoritative SQL transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from infrastructure.persistence.postgresql.models.project_activity_model import ProjectActivityModel

EVENT_TYPES = frozenset({
    "PROJECT_CREATED", "DESIGN_APPROVED", "METHOD_ACTIVATED",
    "DESK_REPORT_DRAFT_CREATED", "DESK_REVIEW_ATTENTION",
    "QUANT_REVIEW_ATTENTION", "QUANT_REVIEW_APPROVED",
    "QUANT_APPROVED_REVISION_CREATED",
    "QUANT_PDF_GENERATED", "QUANT_PPTX_GENERATED",
    "QUAL_RUN_CREATED", "QUAL_SESSION_CREATED", "QUAL_ARTIFACT_ACCEPTED",
    "QUAL_TRANSCRIPTION_STARTED", "QUAL_TRANSCRIPTION_COMPLETED", "QUAL_TRANSCRIPTION_FAILED",
    "QUAL_TRANSCRIPT_READY", "QUAL_TRANSCRIPT_DOCX_GENERATED", "QUAL_AUTHORITY_READY",
    "QUAL_ANALYSIS_CORPUS_FROZEN", "QUAL_CODEBOOK_REVISION_CREATED", "QUAL_AI_CODING_COMPLETED",
    "QUAL_CODING_REVISION_ACCEPTED", "QUAL_THEMATIC_REVISION_CREATED",
    "QUAL_THEMATIC_ANALYSIS_ACCEPTED", "QUAL_READY_FOR_FINDINGS",
    "QUAL_FINDINGS_REVISION_CREATED", "QUAL_AI_FINDINGS_READY", "QUAL_FINDING_ACCEPTED",
    "QUAL_INSIGHT_ACCEPTED", "QUAL_REVIEW_REQUESTED", "QUAL_REVIEW_CHANGES_REQUIRED",
    "QUAL_REVIEW_APPROVED", "QUAL_APPROVED_REVISION_CREATED", "QUAL_READY_FOR_DELIVERABLES",
})


def utc_timestamp(value: str | datetime | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def record_activity(
    session: Session, *, project_id: str, semantic_key: str, event_type: str,
    source_kind: str, source_id: str | None = None, occurred_at: str | datetime | None = None,
    method: str | None = None, run_id: str | None = None, actor_id: str | None = None,
    verdict: str | None = None,
) -> None:
    if event_type not in EVENT_TYPES or method not in (None, "DESK", "QUANTITATIVE", "QUALITATIVE") or verdict not in (None, "REVISE", "REJECT"):
        raise ValueError("Invalid Project Activity catalogue value")
    if source_kind not in {"project", "design", "run", "study", "report", "review", "revision", "deliverable", "session", "qual_artifact", "transcription_job", "transcript", "transcript_export", "qual_analysis_corpus", "qual_codebook", "qual_ai_proposal", "qual_coding", "qual_thematic_analysis", "qual_finding", "qual_insight", "qual_post_analysis_revision", "qual_review", "qual_approved_revision"}:
        raise ValueError("Invalid Project Activity source")
    timestamp = utc_timestamp(occurred_at) if occurred_at is not None else datetime.now(UTC)
    if timestamp is None:
        raise ValueError("Project Activity needs a timezone-aware timestamp")
    session.add(ProjectActivityModel(
        event_id=str(uuid5(NAMESPACE_URL, f"project-activity:{project_id}:{semantic_key}")),
        project_id=project_id, semantic_key=semantic_key, event_type=event_type,
        occurred_at=timestamp, method=method, run_id=run_id, actor_id=actor_id,
        source_kind=source_kind, source_id=source_id, verdict=verdict,
    ))
