from __future__ import annotations

from typing import Any

from domain.ai.prompt import Prompt
from domain.reviews.review_issue import ReviewIssueSeverity, ReviewIssueType

from application.ports.review_ports import (
    ReviewIssueCandidate,
    ReviewSectionInput,
    SemanticReviewInput,
)
from application.review.exceptions import ReviewConfigurationError
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from infrastructure.llm.llm_client import LLMClient

_VALID_ISSUE_TYPES = {member.value for member in ReviewIssueType}
_VALID_SEVERITIES = {member.value for member in ReviewIssueSeverity}


class LlmReviewEngine:
    """Production semantic reviewer using bounded structured LLM output (DR-07)."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_chars_per_section: int = 8000,
        max_issues_per_section: int = 5,
    ) -> None:
        self._llm_client = llm_client
        self._max_chars_per_section = max_chars_per_section
        self._max_issues_per_section = max_issues_per_section
        self._json_extractor = JsonExtractor()
        self._json_validator = JsonValidator()

    def review_report(
        self,
        review_input: SemanticReviewInput,
    ) -> tuple[ReviewIssueCandidate, ...]:
        candidates: list[ReviewIssueCandidate] = []
        for section_input in review_input.section_inputs:
            prompt = Prompt(
                system=self._system_prompt(),
                user=self._build_section_payload(review_input, section_input),
            )
            try:
                response = self._llm_client.generate(prompt)
            except Exception as exc:
                raise ReviewConfigurationError("LLM semantic review failed") from exc

            payload = self._parse_payload(response.content)
            candidates.extend(
                self._map_issues(
                    payload,
                    review_input=review_input,
                    section_input=section_input,
                ),
            )
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

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are an independent desk-research quality reviewer. "
            "Assess whether report prose is supported by the referenced Findings "
            "and Insights. Flag probable unsupported or overstated claims, hidden "
            "contradictions, missing major caveats, and weak answers to research "
            "questions. Do NOT provide chain-of-thought. "
            "Return JSON only with shape "
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
            "Use only IDs from the provided section context. "
            "If no semantic issues exist, return {\"issues\":[]}."
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

    def _parse_payload(self, content: str) -> dict[str, Any]:
        for candidate in self._json_extractor.extract_all(content):
            validation = self._json_validator.validate(candidate)
            if validation.is_valid and isinstance(validation.data, dict):
                return validation.data
        raise ValueError("LLM review payload must be a JSON object")

    def _map_issues(
        self,
        payload: dict[str, Any],
        *,
        review_input: SemanticReviewInput,
        section_input: ReviewSectionInput,
    ) -> list[ReviewIssueCandidate]:
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
        for item in payload.get("issues", []):
            if len(mapped) >= self._max_issues_per_section:
                break
            if not isinstance(item, dict):
                continue

            issue_type = str(item.get("issue_type", "")).strip()
            severity = str(item.get("severity", "")).strip()
            message = str(item.get("message", "")).strip()
            if issue_type not in _VALID_ISSUE_TYPES:
                continue
            if severity not in _VALID_SEVERITIES:
                continue
            if not message:
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
                continue

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
                    suggested_action=str(item.get("suggested_action", "")).strip(),
                    metadata=(
                        dict(item["metadata"])
                        if isinstance(item.get("metadata"), dict)
                        else {}
                    ),
                ),
            )
        return mapped
