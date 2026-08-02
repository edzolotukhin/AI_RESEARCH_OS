from __future__ import annotations

from typing import Any

from application.ports.report_ports import (
    ReportCandidate,
    ReportInput,
    ReportSectionCandidate,
)
from application.report.exceptions import ReportConfigurationError
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


class LlmReportEngine:
    """Production report writer using structured LLM output."""

    method_name = "llm"

    def __init__(self, *, llm_client: LLMClient) -> None:
        self._llm_client = llm_client
        self._json_extractor = JsonExtractor()
        self._json_validator = JsonValidator()

    def generate_sections(
        self,
        report_input: ReportInput,
    ) -> tuple[ReportSectionCandidate, ...]:
        prompt = Prompt(
            system=(
                "You are a desk research report writer. You synthesize validated Findings "
                "and Insights into readable report sections. You MUST NOT invent new facts, "
                "perform web research, or reference IDs not provided. Return JSON only with "
                'shape {"sections":[{"title":"...","content":"...",'
                '"finding_refs":["finding-id"],"insight_refs":["insight-id"],'
                '"research_question_refs":["rq-id"],"evidence_refs":["evidence-id"]}]}. '
                "Each section must reference at least one finding_ref or insight_ref. "
                f"Write in language '{report_input.brief.language}'."
            ),
            user=self._build_section_payload(report_input),
        )
        try:
            response = self._llm_client.generate(prompt)
        except Exception as exc:
            raise ReportConfigurationError("LLM report section generation failed") from exc

        payload = self._parse_payload(response.content)
        allowed_findings = {item.id for item in report_input.findings}
        allowed_insights = {item.id for item in report_input.insights}
        allowed_evidence = set(report_input.evidence_by_id)
        allowed_questions = {
            question.id for question in report_input.design.research_questions
        }
        sections: list[ReportSectionCandidate] = []
        for item in payload.get("sections", []):
            if not isinstance(item, dict):
                continue
            finding_refs = tuple(
                str(ref).strip()
                for ref in item.get("finding_refs", [])
                if str(ref).strip() in allowed_findings
            )
            insight_refs = tuple(
                str(ref).strip()
                for ref in item.get("insight_refs", [])
                if str(ref).strip() in allowed_insights
            )
            if not finding_refs and not insight_refs:
                continue
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if not title or not content:
                continue
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
        return tuple(sections)

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
            response = self._llm_client.generate(prompt)
        except Exception as exc:
            raise ReportConfigurationError("LLM executive summary generation failed") from exc

        payload = self._parse_payload(response.content)
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

    def _parse_payload(self, content: str) -> dict[str, Any]:
        extracted = self._json_extractor.extract(content)
        self._json_validator.validate(extracted)
        if not isinstance(extracted, dict):
            raise ReportConfigurationError("LLM report payload must be a JSON object")
        return extracted

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
