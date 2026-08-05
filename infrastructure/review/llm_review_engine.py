from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError
from application.review.exceptions import ReviewConfigurationError
from application.review.review_structured_output import (
    DEFAULT_REVIEW_MAX_MESSAGE_CHARS,
    DEFAULT_REVIEW_MAX_SUGGESTED_ACTION_CHARS,
    REVIEW_ISSUES_PAYLOAD_SCHEMA,
    ReviewStructuredOutputGenerator,
)
from domain.ai.prompt import Prompt
from domain.reviews.review_issue import ReviewIssueSeverity, ReviewIssueType

from application.ports.review_ports import (
    ReviewIssueCandidate,
    ReviewSectionInput,
    SemanticReviewInput,
)
from infrastructure.llm.llm_client import LLMClient

_VALID_ISSUE_TYPES = {member.value for member in ReviewIssueType}
_VALID_SEVERITIES = {member.value for member in ReviewIssueSeverity}


@dataclass
class ReviewSectionEngineStats:
    candidate_review_count: int = 0
    engine_dropped_count: int = 0
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    parse_failure_category: str | None = None
    contract_failure_category: str | None = None
    attempts: int = 1
    rejection_counts: dict[str, int] = field(default_factory=dict)


class LlmReviewEngine:
    """Production semantic reviewer using bounded structured LLM output (DR-07)."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_chars_per_section: int = 8000,
        max_issues_per_section: int = 5,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        structured_output_max_attempts: int = 3,
        max_message_chars: int = DEFAULT_REVIEW_MAX_MESSAGE_CHARS,
        max_suggested_action_chars: int = DEFAULT_REVIEW_MAX_SUGGESTED_ACTION_CHARS,
    ) -> None:
        self._structured_output = ReviewStructuredOutputGenerator(
            llm_client=llm_client,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            max_attempts=structured_output_max_attempts,
        )
        self._max_chars_per_section = max_chars_per_section
        self._max_issues_per_section = max_issues_per_section
        self._max_message_chars = max_message_chars
        self._max_suggested_action_chars = max_suggested_action_chars
        self._last_section_stats: ReviewSectionEngineStats | None = None
        self._section_stats: list[ReviewSectionEngineStats] = []

    @property
    def last_section_stats(self) -> ReviewSectionEngineStats | None:
        return self._last_section_stats

    @property
    def section_stats(self) -> tuple[ReviewSectionEngineStats, ...]:
        return tuple(self._section_stats)

    def review_report(
        self,
        review_input: SemanticReviewInput,
    ) -> tuple[ReviewIssueCandidate, ...]:
        candidates: list[ReviewIssueCandidate] = []
        self._section_stats = []
        for section_input in review_input.section_inputs:
            prompt = Prompt(
                system=self._system_prompt(),
                user=self._build_section_payload(review_input, section_input),
            )
            try:
                payload = self._structured_output.generate(
                    prompt,
                    payload_schema=REVIEW_ISSUES_PAYLOAD_SCHEMA,
                )
            except StructuredOutputError as exc:
                telemetry = self._structured_output.last_telemetry
                stats = ReviewSectionEngineStats(
                    parse_failure_category=(
                        telemetry.parse_failure_category if telemetry else "parse_error"
                    ),
                    contract_failure_category=(
                        telemetry.contract_failure_category if telemetry else None
                    ),
                    output_tokens=telemetry.output_tokens if telemetry else None,
                    reasoning_tokens=telemetry.reasoning_tokens if telemetry else None,
                    visible_output_length=(
                        telemetry.visible_output_length if telemetry else None
                    ),
                    finish_reason=telemetry.finish_reason if telemetry else None,
                    max_output_tokens=telemetry.max_output_tokens if telemetry else None,
                    reasoning_effort=telemetry.reasoning_effort if telemetry else None,
                    attempts=telemetry.attempts if telemetry else 1,
                )
                self._last_section_stats = stats
                self._section_stats.append(stats)
                raise ReviewConfigurationError(
                    "LLM semantic review failed structured output validation",
                ) from exc
            except Exception as exc:
                raise ReviewConfigurationError("LLM semantic review failed") from exc

            mapped, stats = self._map_issues(
                payload,
                review_input=review_input,
                section_input=section_input,
            )
            telemetry = self._structured_output.last_telemetry
            if telemetry is not None:
                stats.output_tokens = telemetry.output_tokens
                stats.reasoning_tokens = telemetry.reasoning_tokens
                stats.visible_output_length = telemetry.visible_output_length
                stats.finish_reason = telemetry.finish_reason
                stats.max_output_tokens = telemetry.max_output_tokens
                stats.reasoning_effort = telemetry.reasoning_effort
                stats.attempts = telemetry.attempts
            self._last_section_stats = stats
            self._section_stats.append(stats)
            candidates.extend(mapped)
        return tuple(candidates)

    def max_input_chars_per_request(
        self,
        review_input: SemanticReviewInput,
    ) -> int:
        """Maximum characters passed to a single LLM review request."""
        if not review_input.section_inputs:
            return 0
        return max(
            len(self._build_section_payload(review_input, section_input))
            for section_input in review_input.section_inputs
        )

    def _system_prompt(self) -> str:
        return (
            "You are an independent desk-research quality reviewer. "
            "Assess whether report prose is supported by the referenced Findings "
            "and Insights. Flag probable unsupported or overstated claims, hidden "
            "contradictions, missing major caveats, and weak answers to research "
            "questions. Do NOT provide chain-of-thought. "
            "Return compact JSON only with shape "
            '{"issues":[{"issue_type":"unsupported_claim",'
            '"severity":"major","message":"...",'
            '"finding_refs":["finding-id"],'
            '"insight_refs":["insight-id"],'
            '"evidence_refs":["evidence-id"],'
            '"source_refs":["source-id"],'
            '"research_question_refs":["rq-id"],'
            '"suggested_action":"..."}]}. '
            "issue_type must be one of: "
            f"{', '.join(sorted(_VALID_ISSUE_TYPES))}. "
            "severity must be major or minor. "
            f"Return at most {self._max_issues_per_section} issues. "
            f"Keep each message under {self._max_message_chars} characters. "
            "Do not include full report text in the response. "
            "Use only IDs from the provided section context. "
            'If no semantic issues exist, return {"issues":[]}.'
        )

    def _build_section_payload(
        self,
        review_input: SemanticReviewInput,
        section_input: ReviewSectionInput,
    ) -> str:
        section = review_input.report.sections[section_input.section_index]
        content = section_input.section_content[: self._max_chars_per_section]
        lines = [
            f"brief_objectives: {list(review_input.brief_objectives)}",
            f"research_questions: {list(review_input.research_questions)}",
            f"section_index: {section_input.section_index}",
            f"section_id: {section.id}",
            f"section_title: {section_input.section_title}",
            f"section_content: {content}",
            f"finding_refs: {list(section_input.finding_refs)}",
            f"insight_refs: {list(section_input.insight_refs)}",
            f"citation_ids: {list(section_input.citation_ids)}",
            f"research_question_refs: {list(section_input.research_question_refs)}",
        ]
        if review_input.existing_issues:
            lines.append("existing_structural_issues:")
            for issue in review_input.existing_issues[:10]:
                lines.append(f"- {issue.issue_type.value}: {issue.message[:200]}")
        return "\n".join(lines)

    def _map_issues(
        self,
        payload: dict[str, Any],
        *,
        review_input: SemanticReviewInput,
        section_input: ReviewSectionInput,
    ) -> tuple[list[ReviewIssueCandidate], ReviewSectionEngineStats]:
        section = review_input.report.sections[section_input.section_index]
        allowed_findings = set(section_input.finding_refs)
        allowed_insights = set(section_input.insight_refs)
        allowed_evidence = set(section.evidence_refs)
        allowed_sources = {
            str(entry.get("source_id", "")).strip()
            for entry in (review_input.report.citation_registry or {}).values()
            if isinstance(entry, dict)
        }
        allowed_questions = set(section_input.research_question_refs)

        mapped: list[ReviewIssueCandidate] = []
        rejection_counts: dict[str, int] = {}
        raw_items = 0
        for item in payload.get("issues", []):
            raw_items += 1
            if len(mapped) >= self._max_issues_per_section:
                rejection_counts["max_issues_per_section"] = (
                    rejection_counts.get("max_issues_per_section", 0) + 1
                )
                break
            if not isinstance(item, dict):
                rejection_counts["invalid_item_shape"] = (
                    rejection_counts.get("invalid_item_shape", 0) + 1
                )
                continue

            issue_type = str(item.get("issue_type", "")).strip()
            severity = str(item.get("severity", "")).strip()
            message = str(item.get("message", "")).strip()[: self._max_message_chars]
            if issue_type not in _VALID_ISSUE_TYPES:
                rejection_counts["invalid_issue_type"] = (
                    rejection_counts.get("invalid_issue_type", 0) + 1
                )
                continue
            if severity not in _VALID_SEVERITIES:
                rejection_counts["invalid_severity"] = (
                    rejection_counts.get("invalid_severity", 0) + 1
                )
                continue
            if not message:
                rejection_counts["missing_message"] = (
                    rejection_counts.get("missing_message", 0) + 1
                )
                continue

            raw_finding = [
                str(value).strip() for value in item.get("finding_refs", []) if str(value).strip()
            ]
            raw_insight = [
                str(value).strip() for value in item.get("insight_refs", []) if str(value).strip()
            ]
            raw_evidence = [
                str(value).strip() for value in item.get("evidence_refs", []) if str(value).strip()
            ]
            raw_source = [
                str(value).strip() for value in item.get("source_refs", []) if str(value).strip()
            ]
            raw_question = [
                str(value).strip()
                for value in item.get("research_question_refs", [])
                if str(value).strip()
            ]

            finding_refs = tuple(ref for ref in raw_finding if ref in allowed_findings)
            insight_refs = tuple(ref for ref in raw_insight if ref in allowed_insights)
            evidence_refs = tuple(ref for ref in raw_evidence if ref in allowed_evidence)
            source_refs = tuple(ref for ref in raw_source if ref in allowed_sources)
            question_refs = tuple(ref for ref in raw_question if ref in allowed_questions)

            had_refs = bool(
                raw_finding or raw_insight or raw_evidence or raw_source or raw_question,
            )
            validated_refs = bool(
                finding_refs or insight_refs or evidence_refs or source_refs or question_refs,
            )
            if had_refs and not validated_refs:
                rejection_counts["foreign_refs"] = (
                    rejection_counts.get("foreign_refs", 0) + 1
                )
                continue

            suggested_action = str(item.get("suggested_action", "")).strip()[
                : self._max_suggested_action_chars
            ]
            mapped.append(
                ReviewIssueCandidate(
                    issue_type=issue_type,
                    severity=severity,
                    message=message,
                    report_section_id=section.id,
                    finding_refs=finding_refs,
                    insight_refs=insight_refs,
                    evidence_refs=evidence_refs,
                    source_refs=source_refs,
                    research_question_refs=question_refs,
                    suggested_action=suggested_action,
                    metadata=(
                        dict(item["metadata"])
                        if isinstance(item.get("metadata"), dict)
                        else {}
                    ),
                ),
            )

        stats = ReviewSectionEngineStats(
            candidate_review_count=len(mapped),
            engine_dropped_count=max(0, raw_items - len(mapped)),
            rejection_counts=rejection_counts,
        )
        return mapped, stats
