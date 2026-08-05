from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError
from application.ports.report_ports import (
    ReportCandidate,
    ReportInput,
    ReportSectionCandidate,
)
from application.report.diagnostics import (
    REJECTION_CATEGORY_EMPTY_SUPPORT,
    REJECTION_CATEGORY_INVALID_FINDING_REF,
    REJECTION_CATEGORY_INVALID_INSIGHT_REF,
    REJECTION_CATEGORY_MISSING_CONTENT,
    REJECTION_CATEGORY_MISSING_TITLE,
)
from application.report.exceptions import ReportConfigurationError
from application.report.report_structured_output import (
    REPORT_SECTIONS_PAYLOAD_SCHEMA,
    REPORT_SUMMARY_PAYLOAD_SCHEMA,
    ReportStructuredOutputGenerator,
)
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


@dataclass
class ReportSectionEngineBatchStats:
    candidate_section_count: int = 0
    engine_dropped_count: int = 0
    raw_items: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    parse_failure_category: str | None = None


class LlmReportEngine:
    """Production report writer using structured LLM output."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        max_sections: int = 10,
        max_findings_per_section: int = 15,
        max_insights_per_section: int = 8,
        structured_output_max_attempts: int = 3,
    ) -> None:
        self._structured_output = ReportStructuredOutputGenerator(
            llm_client=llm_client,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            max_attempts=structured_output_max_attempts,
        )
        self._max_sections = max_sections
        self._max_findings_per_section = max_findings_per_section
        self._max_insights_per_section = max_insights_per_section
        self._last_section_batch_stats: ReportSectionEngineBatchStats | None = None

    @property
    def last_section_batch_stats(self) -> ReportSectionEngineBatchStats | None:
        return self._last_section_batch_stats

    def generate_sections(
        self,
        report_input: ReportInput,
    ) -> tuple[ReportSectionCandidate, ...]:
        prompt = Prompt(
            system=self._section_system_prompt(report_input),
            user=self._build_section_payload(report_input),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=REPORT_SECTIONS_PAYLOAD_SCHEMA,
            )
        except StructuredOutputError as exc:
            raise ReportConfigurationError(
                "LLM report section generation failed structured output validation",
            ) from exc
        except Exception as exc:
            raise ReportConfigurationError("LLM report section generation failed") from exc

        sections, stats = self._build_section_candidates(report_input, payload)
        telemetry = self._structured_output.last_telemetry
        if telemetry is not None:
            stats.output_tokens = telemetry.output_tokens
            stats.reasoning_tokens = telemetry.reasoning_tokens
            stats.visible_output_length = telemetry.visible_output_length
            stats.finish_reason = telemetry.finish_reason
            stats.max_output_tokens = telemetry.max_output_tokens
            stats.reasoning_effort = telemetry.reasoning_effort
            stats.parse_failure_category = telemetry.parse_failure_category
        self._last_section_batch_stats = stats
        return sections

    def generate_executive_summary(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> ReportCandidate:
        prompt = Prompt(
            system=(
                "You are a desk research report writer. Produce a report title, executive "
                "summary, and limitations list from validated section summaries. Do NOT "
                "invent new facts or external information. Return JSON only with shape "
                '{"title":"...","executive_summary":"...","limitations":["..."]}. '
                f"Write in language '{report_input.brief.language}'."
            ),
            user=self._build_summary_payload(report_input, sections=sections),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=REPORT_SUMMARY_PAYLOAD_SCHEMA,
            )
        except StructuredOutputError as exc:
            raise ReportConfigurationError(
                "LLM executive summary generation failed structured output validation",
            ) from exc
        except Exception as exc:
            raise ReportConfigurationError("LLM executive summary generation failed") from exc

        title = str(payload.get("title", report_input.brief.title)).strip()
        executive_summary = str(payload.get("executive_summary", "")).strip()
        limitations = tuple(
            str(item).strip()
            for item in payload.get("limitations", [])
            if str(item).strip()
        )
        if not title or not executive_summary:
            raise ReportConfigurationError("LLM report summary missing title or content")
        return ReportCandidate(
            title=title,
            executive_summary=executive_summary,
            sections=sections,
            limitations=limitations,
        )

    def _section_system_prompt(self, report_input: ReportInput) -> str:
        return (
            "You are a desk research report writer. Synthesize validated Findings and "
            "Insights into compact, decision-oriented report sections. You MUST NOT invent "
            "new facts, perform web research, or reference IDs not provided. Consolidate "
            "related findings into major sections rather than repeating every finding. "
            f"Return at most {self._max_sections} sections. Each section may reference up "
            f"to {self._max_findings_per_section} finding_refs and "
            f"{self._max_insights_per_section} insight_refs. Return JSON only with shape "
            '{"sections":[{"title":"...","content":"...",'
            '"finding_refs":["finding-id"],"insight_refs":["insight-id"],'
            '"research_question_refs":["rq-id"],"evidence_refs":["evidence-id"]}]}. '
            "Each section must reference at least one finding_ref or insight_ref. "
            f"Write in language '{report_input.brief.language}'."
        )

    def _build_section_candidates(
        self,
        report_input: ReportInput,
        payload: dict[str, Any],
    ) -> tuple[tuple[ReportSectionCandidate, ...], ReportSectionEngineBatchStats]:
        allowed_findings = {item.id for item in report_input.findings}
        allowed_insights = {item.id for item in report_input.insights}
        allowed_evidence = set(report_input.evidence_by_id)
        allowed_questions = {
            question.id for question in report_input.design.research_questions
        }
        sections: list[ReportSectionCandidate] = []
        rejection_counts: dict[str, int] = {}
        raw_items = 0
        engine_dropped = 0
        seen_titles: set[str] = set()

        for item in payload.get("sections", []):
            raw_items += 1
            if not isinstance(item, dict):
                engine_dropped += 1
                continue

            raw_finding_refs = [
                str(ref).strip() for ref in item.get("finding_refs", []) if str(ref).strip()
            ]
            raw_insight_refs = [
                str(ref).strip() for ref in item.get("insight_refs", []) if str(ref).strip()
            ]
            invalid_finding_refs = [
                ref for ref in raw_finding_refs if ref not in allowed_findings
            ]
            invalid_insight_refs = [
                ref for ref in raw_insight_refs if ref not in allowed_insights
            ]
            if invalid_finding_refs:
                rejection_counts[REJECTION_CATEGORY_INVALID_FINDING_REF] = (
                    rejection_counts.get(REJECTION_CATEGORY_INVALID_FINDING_REF, 0)
                    + len(invalid_finding_refs)
                )
            if invalid_insight_refs:
                rejection_counts[REJECTION_CATEGORY_INVALID_INSIGHT_REF] = (
                    rejection_counts.get(REJECTION_CATEGORY_INVALID_INSIGHT_REF, 0)
                    + len(invalid_insight_refs)
                )

            finding_refs = tuple(
                ref for ref in raw_finding_refs if ref in allowed_findings
            )[: self._max_findings_per_section]
            insight_refs = tuple(
                ref for ref in raw_insight_refs if ref in allowed_insights
            )[: self._max_insights_per_section]
            if not finding_refs and not insight_refs:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_EMPTY_SUPPORT] = (
                    rejection_counts.get(REJECTION_CATEGORY_EMPTY_SUPPORT, 0) + 1
                )
                continue

            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if not title:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_MISSING_TITLE] = (
                    rejection_counts.get(REJECTION_CATEGORY_MISSING_TITLE, 0) + 1
                )
                continue
            if not content:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_MISSING_CONTENT] = (
                    rejection_counts.get(REJECTION_CATEGORY_MISSING_CONTENT, 0) + 1
                )
                continue
            normalized_title = title.lower()
            if normalized_title in seen_titles:
                engine_dropped += 1
                rejection_counts["duplicate_section"] = (
                    rejection_counts.get("duplicate_section", 0) + 1
                )
                continue
            seen_titles.add(normalized_title)

            evidence_refs = tuple(
                str(ref).strip()
                for ref in item.get("evidence_refs", [])
                if str(ref).strip() in allowed_evidence
            )
            question_refs = tuple(
                str(ref).strip()
                for ref in item.get("research_question_refs", [])
                if str(ref).strip() in allowed_questions
            )
            if (
                not question_refs
                and report_input.batch_question_id
                and report_input.batch_question_id in allowed_questions
            ):
                question_refs = (report_input.batch_question_id,)
            sections.append(
                ReportSectionCandidate(
                    title=title,
                    content=content,
                    research_question_refs=question_refs,
                    finding_refs=finding_refs,
                    insight_refs=insight_refs,
                    evidence_refs=evidence_refs,
                ),
            )
            if len(sections) >= self._max_sections:
                break

        stats = ReportSectionEngineBatchStats(
            candidate_section_count=len(sections),
            engine_dropped_count=engine_dropped,
            raw_items=raw_items,
            rejection_counts=rejection_counts,
        )
        return tuple(sections), stats

    def _build_section_payload(self, report_input: ReportInput) -> str:
        lines = [
            f"business_question: {report_input.brief.business_question}",
            f"language: {report_input.brief.language}",
            "deliverable_plan:",
            *[f"- {item}" for item in report_input.section_titles],
            "findings:",
        ]
        for finding in report_input.findings:
            lines.append(
                f"- id={finding.id} statement={finding.statement} "
                f"evidence_refs={list(finding.evidence_refs)}",
            )
        lines.append("insights:")
        for insight in report_input.insights:
            lines.append(
                f"- id={insight.id} statement={insight.statement} "
                f"finding_refs={list(insight.finding_refs)}",
            )
        if report_input.batch_question_id:
            lines.append(f"batch_research_question_id: {report_input.batch_question_id}")
        return "\n".join(lines)

    def _build_summary_payload(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> str:
        lines = [
            f"business_question: {report_input.brief.business_question}",
            f"language: {report_input.brief.language}",
            "section_summaries:",
        ]
        for section in sections:
            lines.append(f"- {section.title}: {section.content[:500]}")
        lines.append("design_limitations:")
        for limitation in report_input.design.limitations:
            lines.append(f"- {limitation}")
        return "\n".join(lines)
