from __future__ import annotations

from application.config import ApplicationConfig
from application.execution.execution_budget import ExecutionBudget
from application.report.content_batching import DEFAULT_REPORT_MAX_SECTIONS


def create_execution_budget(
    config: ApplicationConfig | None = None,
) -> ExecutionBudget:
    """Build a per-run budget from application configuration."""
    resolved = config or ApplicationConfig.from_env()
    return ExecutionBudget(
        evidence_max_items_per_run=resolved.evidence_max_items_per_run,
        evidence_max_items_per_source=resolved.evidence_max_items_per_source,
        analysis_max_findings=resolved.analysis_max_findings,
        analysis_max_insights=resolved.analysis_max_insights,
        report_max_sections=resolved.report_max_sections or DEFAULT_REPORT_MAX_SECTIONS,
        evidence_max_llm_calls=resolved.evidence_max_llm_calls,
        analysis_max_llm_calls=resolved.analysis_max_llm_calls,
        report_max_llm_calls=resolved.report_max_llm_calls,
        review_max_llm_calls=resolved.review_max_calls,
        llm_max_calls_per_run=resolved.llm_max_calls_per_run,
    )
