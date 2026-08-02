from __future__ import annotations

from domain.sources.source import Source

from api.schemas.sources import SourceResponse

_CONTENT_PREVIEW_LIMIT = 500


def source_to_response(source: Source) -> SourceResponse:
    preview = source.content_text[:_CONTENT_PREVIEW_LIMIT]
    if len(source.content_text) > _CONTENT_PREVIEW_LIMIT:
        preview = f"{preview}..."
    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        url=source.url,
        canonical_url=source.canonical_url,
        title=source.title,
        publisher=source.publisher,
        author=source.author,
        published_at=source.published_at,
        retrieved_at=source.retrieved_at,
        source_type=source.source_type,
        language=source.language,
        content_type=source.content_type,
        query_refs=list(source.query_refs),
        research_question_refs=list(source.research_question_refs),
        information_need_refs=list(source.information_need_refs),
        workflow_run_refs=list(source.workflow_run_refs),
        research_design_refs=list(source.research_design_refs),
        retrieval_status=source.retrieval_status.value,
        content_preview=preview,
        content_checksum=source.content_checksum,
        metadata=dict(source.metadata),
    )
