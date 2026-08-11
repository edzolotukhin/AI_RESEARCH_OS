"""LLM-backed Finding ↔ Evidence entailment validator (Analysis-stage client)."""

from __future__ import annotations

from typing import Any

from application.analysis.exceptions import (
    AnalysisConfigurationError,
    FindingEntailmentError,
)
from application.analysis.finding_entailment import (
    EntailmentCandidateProjection,
    FindingEntailmentStatus,
    FindingEntailmentVerdict,
    parse_entailment_payload,
)
from application.execution.exceptions import BudgetExhaustedError
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_validator import JsonValidator
from domain.ai.prompt import Prompt
from infrastructure.llm.generation_options import LLMGenerationOptions
from infrastructure.llm.llm_client import LLMClient


_SYSTEM_PROMPT = (
    "You are an independent entailment validator for desk-research Findings. "
    "You did NOT generate the Findings. Judge whether each Finding.statement "
    "(and material claims in rationale) is semantically supported by the "
    "referenced Evidence statement/source_excerpt bodies only. "
    "Return JSON only with shape "
    '{"verdicts":[{"candidate_id":"fc-0001","status":"SUPPORTED",'
    '"supported_evidence_ids":["evidence-id"],'
    '"unsupported_claim_parts":[],"rationale":"..."}]}. '
    "status MUST be one of: SUPPORTED, PARTIAL, UNSUPPORTED, CONTRADICTED, "
    "INSUFFICIENT_EVIDENCE. "
    "Rules: "
    "DIRECT quantitative support (e.g. 41%→48% entails +7pp) → SUPPORTED. "
    "Justified multi-evidence synthesis of the same claim family → SUPPORTED. "
    "Overstatement beyond Evidence (e.g. market leadership from awareness only) "
    "→ UNSUPPORTED or PARTIAL. "
    "Finding contradicts Evidence → CONTRADICTED. "
    "Semantically unrelated claim with valid Evidence ids → UNSUPPORTED. "
    "Weak/context-only Evidence for a strong quantitative Finding → "
    "INSUFFICIENT_EVIDENCE. "
    "Materially conflicting referenced Evidence → CONTRADICTED or "
    "INSUFFICIENT_EVIDENCE; never SUPPORTED. "
    "If any input field is marked truncated, do not return SUPPORTED; use "
    "INSUFFICIENT_EVIDENCE. "
    "supported_evidence_ids MUST be a subset of that candidate's evidence_refs. "
    "Emit exactly one verdict per submitted candidate_id; no extras, no omissions."
)


class LlmFindingEntailmentValidator:
    """Separate Analysis-stage LLM invocation; structured fail-closed parse."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._json_extractor = JsonExtractor()
        self._json_validator = JsonValidator()
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort

    def validate_batch(
        self,
        projections: list[EntailmentCandidateProjection],
    ) -> list[FindingEntailmentVerdict]:
        if not projections:
            return []
        prompt = Prompt(
            system=_SYSTEM_PROMPT,
            user=self._build_user_payload(projections),
        )
        try:
            response = self._llm_client.generate(
                prompt,
                options=LLMGenerationOptions(
                    max_output_tokens=self._max_output_tokens,
                    reasoning_effort=self._reasoning_effort,
                ),
            )
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            raise AnalysisConfigurationError(
                "LLM finding entailment validation failed",
            ) from exc

        payload = self._parse_payload(response.content)
        return parse_entailment_payload(payload, submitted=projections)

    def _build_user_payload(
        self,
        projections: list[EntailmentCandidateProjection],
    ) -> str:
        lines = [
            "Validate each Finding candidate against its referenced Evidence bodies.",
            "candidates:",
        ]
        for item in projections:
            lines.append(f"- candidate_id={item.candidate_id}")
            lines.append(f"  statement={item.statement}")
            lines.append(f"  rationale={item.rationale}")
            lines.append(f"  evidence_refs={list(item.evidence_refs)}")
            if item.research_question_text:
                lines.append(f"  research_question={item.research_question_text}")
            lines.append(f"  input_truncated={str(item.truncated).lower()}")
            lines.append("  evidence:")
            for evidence in item.evidence:
                lines.append(
                    f"    - id={evidence.id} truncated={str(evidence.truncated).lower()} "
                    f"statement={evidence.statement} "
                    f"source_excerpt={evidence.source_excerpt}",
                )
        return "\n".join(lines)

    def _parse_payload(self, content: str) -> dict[str, Any]:
        for candidate in self._json_extractor.extract_all(content):
            validation = self._json_validator.validate(candidate)
            if validation.is_valid and isinstance(validation.data, dict):
                return validation.data
        raise FindingEntailmentError(
            "Entailment validator payload must be a JSON object",
        )


# Re-export status for engine diagnostics convenience.
SUPPORTED = FindingEntailmentStatus.SUPPORTED
