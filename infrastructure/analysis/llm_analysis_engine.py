from __future__ import annotations

from typing import Any

from domain.findings.finding_type import FindingType

from application.analysis.exceptions import AnalysisConfigurationError
from application.ports.analysis_ports import (
    AnalysisInput,
    FindingCandidate,
    InsightCandidate,
)
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


class LlmAnalysisEngine:
    """Production analysis engine using structured LLM output."""

    method_name = "llm"

    def __init__(self, *, llm_client: LLMClient) -> None:
        self._llm_client = llm_client
        self._json_extractor = JsonExtractor()
        self._json_validator = JsonValidator()

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        prompt = Prompt(
            system=(
                "You are a desk research analyst. Evidence is grounded factual material. "
                "A Finding is an analytical conclusion supported by Evidence IDs. "
                "Do NOT treat Evidence and Finding as interchangeable. "
                "Return JSON only with shape "
                '{"findings":[{"statement":"...","rationale":"...",'
                '"evidence_refs":["evidence-id"],'
                '"research_question_refs":["rq-id"],'
                '"information_need_refs":["in-id"],'
                '"finding_type":"synthesis",'
                '"confidence":0.7}]}. '
                "evidence_refs MUST use only IDs from the provided evidence list. "
                "If evidence conflicts, use finding_type=contradiction and include "
                "all relevant evidence_refs without fabricating resolution. "
                "If evidence does not justify a conclusion, omit that finding."
            ),
            user=self._build_finding_payload(analysis_input),
        )
        try:
            response = self._llm_client.generate(prompt)
        except Exception as exc:
            raise AnalysisConfigurationError("LLM finding analysis failed") from exc

        payload = self._parse_payload(response.content)
        allowed_evidence = {item.id for item in analysis_input.evidence_batch}
        allowed_questions = {
            question.id for question in analysis_input.design.research_questions
        }
        allowed_needs = {need.id for need in analysis_input.design.information_needs}
        candidates: list[FindingCandidate] = []

        for item in payload.get("findings", []):
            if not isinstance(item, dict):
                continue
            evidence_refs = tuple(
                str(ref).strip()
                for ref in item.get("evidence_refs", [])
                if str(ref).strip() in allowed_evidence
            )
            if not evidence_refs:
                continue
            statement = str(item.get("statement", "")).strip()
            rationale = str(item.get("rationale", "")).strip()
            if not statement or not rationale:
                continue
            finding_type = str(item.get("finding_type", FindingType.SYNTHESIS.value))
            if finding_type not in {member.value for member in FindingType}:
                finding_type = FindingType.SYNTHESIS.value
            question_refs = tuple(
                str(ref).strip()
                for ref in item.get("research_question_refs", [])
                if str(ref).strip() in allowed_questions
            )
            need_refs = tuple(
                str(ref).strip()
                for ref in item.get("information_need_refs", [])
                if str(ref).strip() in allowed_needs
            )
            confidence = item.get("confidence")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if finding_type == FindingType.CONTRADICTION.value:
                metadata = {**metadata, "conflicting_evidence": True}
            candidates.append(
                FindingCandidate(
                    statement=statement,
                    rationale=rationale,
                    evidence_refs=evidence_refs,
                    research_question_refs=question_refs,
                    information_need_refs=need_refs,
                    finding_type=finding_type,
                    confidence=float(confidence) if confidence is not None else None,
                    metadata=metadata,
                ),
            )
        return candidates

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        prompt = Prompt(
            system=(
                "You are a desk research analyst. A Finding is an analytical conclusion. "
                "An Insight is an interpretation/implication of Findings in the research "
                "context. Do NOT treat Findings and Insights as interchangeable. "
                "Return JSON only with shape "
                '{"insights":[{"statement":"...","implication":"...",'
                '"finding_refs":["finding-id"],'
                '"research_question_refs":["rq-id"],'
                '"confidence":0.7}]}. '
                "finding_refs MUST use only IDs from the provided findings list."
            ),
            user=self._build_insight_payload(analysis_input),
        )
        try:
            response = self._llm_client.generate(prompt)
        except Exception as exc:
            raise AnalysisConfigurationError("LLM insight analysis failed") from exc

        payload = self._parse_payload(response.content)
        allowed_findings = {item.id for item in analysis_input.persisted_findings}
        allowed_questions = {
            question.id for question in analysis_input.design.research_questions
        }
        candidates: list[InsightCandidate] = []

        for item in payload.get("insights", []):
            if not isinstance(item, dict):
                continue
            finding_refs = tuple(
                str(ref).strip()
                for ref in item.get("finding_refs", [])
                if str(ref).strip() in allowed_findings
            )
            if not finding_refs:
                continue
            statement = str(item.get("statement", "")).strip()
            implication = str(item.get("implication", "")).strip()
            if not statement or not implication:
                continue
            question_refs = tuple(
                str(ref).strip()
                for ref in item.get("research_question_refs", [])
                if str(ref).strip() in allowed_questions
            )
            confidence = item.get("confidence")
            candidates.append(
                InsightCandidate(
                    statement=statement,
                    implication=implication,
                    finding_refs=finding_refs,
                    research_question_refs=question_refs,
                    confidence=float(confidence) if confidence is not None else None,
                    metadata=(
                        dict(item["metadata"])
                        if isinstance(item.get("metadata"), dict)
                        else None
                    ),
                ),
            )
        return candidates

    def _build_finding_payload(self, analysis_input: AnalysisInput) -> str:
        lines = [
            f"research_objective: {analysis_input.brief.business_question}",
            "analysis_plan:",
        ]
        if analysis_input.batch_question_id is not None:
            lines.append(
                f"batch_research_question_id: {analysis_input.batch_question_id}",
            )
        for step in analysis_input.design.analysis_plan:
            lines.append(f"- {step}")
        lines.append("research_questions:")
        for question in analysis_input.design.research_questions:
            lines.append(f"- id={question.id} question={question.question}")
        lines.append("evidence:")
        for evidence in analysis_input.evidence_batch:
            lines.append(
                f"- id={evidence.id} statement={evidence.statement} "
                f"questions={list(evidence.research_question_refs)}",
            )
        return "\n".join(lines)

    def _build_insight_payload(self, analysis_input: AnalysisInput) -> str:
        lines = [
            f"research_objective: {analysis_input.brief.business_question}",
            "analysis_plan:",
        ]
        for step in analysis_input.design.analysis_plan:
            lines.append(f"- {step}")
        lines.append("findings:")
        for finding in analysis_input.persisted_findings:
            lines.append(
                f"- id={finding.id} statement={finding.statement} "
                f"rationale={finding.rationale}",
            )
        return "\n".join(lines)

    def _parse_payload(self, content: str) -> dict[str, Any]:
        for candidate in self._json_extractor.extract_all(content):
            validation = self._json_validator.validate(candidate)
            if validation.is_valid and isinstance(validation.data, dict):
                return validation.data
        raise ValueError("LLM analysis payload must be a JSON object")
