from __future__ import annotations

from domain.evidence.evidence import Evidence


DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH = 20
DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH = 12000


def batch_evidence_by_question(
    evidence_items: list[Evidence],
    *,
    max_evidence_per_batch: int = DEFAULT_ANALYSIS_MAX_EVIDENCE_PER_BATCH,
    max_chars_per_batch: int = DEFAULT_ANALYSIS_MAX_CHARS_PER_BATCH,
) -> list[tuple[str, tuple[Evidence, ...]]]:
    """Group run-scoped Evidence into bounded batches per ResearchQuestion.

    Evidence linked to multiple questions is included in each relevant
    question-specific batch. Durable Finding deduplication prevents duplicate
    analytical records when semantic output is identical across batches.
    """

    grouped: dict[str, list[Evidence]] = {}
    unscoped: list[Evidence] = []
    for evidence in evidence_items:
        if evidence.research_question_refs:
            for question_id in evidence.research_question_refs:
                grouped.setdefault(question_id, []).append(evidence)
        else:
            unscoped.append(evidence)
    if unscoped:
        grouped.setdefault("__unscoped__", []).extend(unscoped)

    batches: list[tuple[str, tuple[Evidence, ...]]] = []
    for question_id, items in grouped.items():
        current: list[Evidence] = []
        current_chars = 0
        for evidence in items:
            statement_len = len(evidence.statement) + len(evidence.source_excerpt)
            would_exceed_count = len(current) >= max_evidence_per_batch
            would_exceed_chars = (
                current
                and current_chars + statement_len > max_chars_per_batch
            )
            if would_exceed_count or would_exceed_chars:
                batches.append((question_id, tuple(current)))
                current = []
                current_chars = 0
            current.append(evidence)
            current_chars += statement_len
        if current:
            batches.append((question_id, tuple(current)))
    return batches
