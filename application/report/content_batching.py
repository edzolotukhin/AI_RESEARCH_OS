from __future__ import annotations

from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief


DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH = 20
DEFAULT_REPORT_MAX_CHARS_PER_BATCH = 12000
DEFAULT_REPORT_MAX_SECTIONS = 10
DEFAULT_REPORT_MAX_FINDINGS_PER_SECTION = 15
DEFAULT_REPORT_MAX_INSIGHTS_PER_SECTION = 8
DEFAULT_REPORT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_REPORT_STRUCTURED_OUTPUT_MAX_ATTEMPTS = 3
DEFAULT_REPORT_MAX_RQ_CORRECTION_ATTEMPTS = 2


def resolve_section_titles(
    *,
    brief: ResearchBrief,
    design: ResearchDesign,
) -> tuple[str, ...]:
    if design.deliverable_plan:
        return design.deliverable_plan
    if brief.deliverables:
        return brief.deliverables
    return tuple(question.question for question in design.research_questions)


def batch_findings_by_question(
    findings: list[Finding],
    *,
    max_findings_per_batch: int = DEFAULT_REPORT_MAX_FINDINGS_PER_BATCH,
    max_chars_per_batch: int = DEFAULT_REPORT_MAX_CHARS_PER_BATCH,
) -> list[tuple[str, tuple[Finding, ...]]]:
    grouped: dict[str, list[Finding]] = {}
    unscoped: list[Finding] = []
    for finding in findings:
        if finding.research_question_refs:
            for question_id in finding.research_question_refs:
                grouped.setdefault(question_id, []).append(finding)
        else:
            unscoped.append(finding)
    if unscoped:
        grouped.setdefault("__unscoped__", []).extend(unscoped)

    batches: list[tuple[str, tuple[Finding, ...]]] = []
    for question_id, items in grouped.items():
        current: list[Finding] = []
        current_chars = 0
        for finding in items:
            statement_len = len(finding.statement) + len(finding.rationale)
            would_exceed_count = len(current) >= max_findings_per_batch
            would_exceed_chars = (
                current and current_chars + statement_len > max_chars_per_batch
            )
            if would_exceed_count or would_exceed_chars:
                batches.append((question_id, tuple(current)))
                current = []
                current_chars = 0
            current.append(finding)
            current_chars += statement_len
        if current:
            batches.append((question_id, tuple(current)))
    return batches


def insights_for_question(
    insights: list[Insight],
    question_id: str,
) -> tuple[Insight, ...]:
    if question_id == "__unscoped__":
        return tuple(item for item in insights if not item.research_question_refs)
    return tuple(
        item for item in insights if question_id in item.research_question_refs
    )
