from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.exceptions import BudgetExhaustedError
from application.research_quality.semantic_sufficiency_contract import (
    SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA,
)
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.evidence_payload import build_evidence_payload
from application.research_quality.sufficiency_diagnostics import (
    format_sufficiency_failure_message,
)
from infrastructure.research_quality.sufficiency_failure_diagnostics import (
    build_sufficiency_failure_diagnostics,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS,
    DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    SufficiencyStructuredOutputGenerator,
)
from domain.ai.prompt import Prompt
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.sufficiency_status import SufficiencyStatus
from infrastructure.llm.llm_client import LLMClient

from application.ports.research_quality_ports import SemanticSufficiencyAssessor

logger = logging.getLogger(__name__)


class LlmSemanticSufficiencyAssessor(SemanticSufficiencyAssessor):
    """LLM-backed semantic sufficiency assessor with bounded structured output."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_output_tokens: int | None = DEFAULT_SUFFICIENCY_MAX_OUTPUT_TOKENS,
        reasoning_effort: str | None = None,
        structured_output_max_attempts: int = (
            DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS
        ),
    ) -> None:
        self._structured_output = SufficiencyStructuredOutputGenerator(
            llm_client=llm_client,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            max_attempts=structured_output_max_attempts,
        )

    def assess(
        self,
        *,
        research_question: ResearchQuestion,
        information_need: InformationNeed,
        evidence: Sequence[Evidence],
        deterministic_signals: DeterministicSufficiencySignals,
    ) -> SemanticSufficiencyAssessment:
        prompt = Prompt(
            system=_system_prompt(),
            user=_build_user_payload(
                research_question=research_question,
                information_need=information_need,
                evidence=evidence,
                deterministic_signals=deterministic_signals,
            ),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=SEMANTIC_SUFFICIENCY_PAYLOAD_SCHEMA,
            )
        except BudgetExhaustedError:
            raise
        except StructuredOutputError as exc:
            telemetry = self._structured_output.last_telemetry
            diagnostics = build_sufficiency_failure_diagnostics(
                structured_error=exc,
                telemetry=telemetry,
            )
            logger.error(
                "sufficiency_structured_output_failed diagnostics=%s",
                diagnostics.to_dict(),
            )
            raise SemanticSufficiencyAssessmentError(
                format_sufficiency_failure_message(diagnostics),
                cause=exc,
                diagnostics=diagnostics,
            ) from exc
        return _payload_to_assessment(payload)


def _payload_to_assessment(payload: dict[str, Any]) -> SemanticSufficiencyAssessment:
    gap_types = tuple(
        GapType(str(value)) for value in payload.get("gap_types", [])
    )
    missing_aspects = tuple(
        str(value).strip()
        for value in payload.get("missing_aspects", [])
        if str(value).strip()
    )
    search_directives = tuple(
        sorted(
            {
                str(value).strip()
                for value in payload.get("search_directives", [])
                if str(value).strip()
            },
        ),
    )
    confidence = payload.get("confidence")
    return SemanticSufficiencyAssessment(
        status=SufficiencyStatus(str(payload["status"])),
        missing_aspects=missing_aspects,
        gap_types=gap_types,
        search_directives=search_directives,
        confidence=float(confidence) if confidence is not None else None,
        reason=str(payload.get("reason", "")).strip(),
    )


def _system_prompt() -> str:
    return (
        "You assess whether existing research evidence substantively answers one "
        "InformationNeed within an existing ResearchQuestion. "
        "Do not propose new research questions, information needs, replanning, "
        "report writing, or broad market research. "
        "Do not suggest external source discovery beyond short targeted search "
        "directives scoped to the current InformationNeed. "
        "Return compact JSON only."
    )


def _build_user_payload(
    *,
    research_question: ResearchQuestion,
    information_need: InformationNeed,
    evidence: Sequence[Evidence],
    deterministic_signals: DeterministicSufficiencySignals,
) -> str:
    deterministic_facts = {
        "evidence_count": deterministic_signals.evidence_count,
        "independent_source_count": deterministic_signals.independent_source_count,
        "freshness_available": deterministic_signals.freshness_available,
        "freshness_score": deterministic_signals.freshness_score,
        "source_quality_available": deterministic_signals.source_quality_available,
        "source_quality_score": deterministic_signals.source_quality_score,
        "source_diversity_available": deterministic_signals.source_diversity_available,
        "source_diversity_score": deterministic_signals.source_diversity_score,
        "quantitative_evidence_present": (
            deterministic_signals.quantitative_evidence_present
        ),
        "contradictions": list(deterministic_signals.contradictions),
        "deterministic_gap_types": [
            gap_type.value for gap_type in deterministic_signals.deterministic_gap_types
        ],
        "warnings": list(deterministic_signals.warnings),
    }
    body = {
        "research_question": {
            "id": research_question.id,
            "question": research_question.question,
        },
        "information_need": {
            "id": information_need.id,
            "description": information_need.description,
        },
        "deterministic_facts": deterministic_facts,
        "evidence": build_evidence_payload(evidence),
    }
    return json.dumps(body, indent=2, sort_keys=True)
