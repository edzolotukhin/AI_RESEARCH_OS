from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from application.exceptions.structured_output_error import StructuredOutputError
from application.execution.exceptions import BudgetExhaustedError
from application.research_quality.allowed_aspect_ids import resolve_allowed_aspect_ids
from application.research_quality.exceptions import SemanticSufficiencyAssessmentError
from application.research_quality.evidence_payload import build_evidence_payload
from application.research_quality.raw_semantic_decision_contract import (
    RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
    raw_semantic_decision_from_payload,
    raw_semantic_decision_payload_contract,
    render_allowed_aspect_contract,
    render_raw_semantic_decision_output_contract,
)
from application.research_quality.semantic_sufficiency_adapter import (
    semantic_assessment_from_raw_decision,
)
from application.research_quality.sufficiency_diagnostics import (
    format_sufficiency_failure_message,
)
from infrastructure.research_quality.sufficiency_failure_diagnostics import (
    build_sufficiency_failure_diagnostics,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    DEFAULT_SUFFICIENCY_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    SufficiencyStructuredOutputGenerator,
)
from domain.ai.prompt import Prompt
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
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
        max_output_tokens: int | None = None,
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
        allowed_aspect_ids = resolve_allowed_aspect_ids(information_need)
        prompt = Prompt(
            system=_system_prompt(allowed_aspect_ids=allowed_aspect_ids),
            user=_build_user_payload(
                research_question=research_question,
                information_need=information_need,
                evidence=evidence,
                deterministic_signals=deterministic_signals,
                allowed_aspect_ids=allowed_aspect_ids,
            ),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
                candidate_validator=raw_semantic_decision_payload_contract,
                allowed_aspect_ids=allowed_aspect_ids,
            )
        except BudgetExhaustedError:
            raise
        except StructuredOutputError as exc:
            telemetry = self._structured_output.last_telemetry
            last_attempt = (
                self._structured_output.attempt_history[-1]
                if self._structured_output.attempt_history
                else None
            )
            diagnostics = build_sufficiency_failure_diagnostics(
                structured_error=exc,
                telemetry=telemetry,
                information_need_id=information_need.id,
                allowed_aspect_ids=allowed_aspect_ids,
                attempt_record=last_attempt,
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
        raw_semantic = raw_semantic_decision_from_payload(payload)
        return semantic_assessment_from_raw_decision(
            information_need=information_need,
            signals=deterministic_signals,
            raw_semantic=raw_semantic,
        )


def _system_prompt(*, allowed_aspect_ids: tuple[str, ...]) -> str:
    return (
        "You evaluate whether existing research evidence semantically supports one "
        "InformationNeed within an existing ResearchQuestion. "
        "Return semantic facts only. "
        "Classify which required aspects are supported, which are missing, and any "
        "substantive contradictions between evidence items. "
        "Do not choose system readiness, final status, gap types, search strategy, "
        "or remediation instructions. "
        "Return compact JSON only.\n\n"
        + render_raw_semantic_decision_output_contract()
        + "\n\n"
        + render_allowed_aspect_contract(allowed_aspect_ids=allowed_aspect_ids)
    )


def _build_user_payload(
    *,
    research_question: ResearchQuestion,
    information_need: InformationNeed,
    evidence: Sequence[Evidence],
    deterministic_signals: DeterministicSufficiencySignals,
    allowed_aspect_ids: tuple[str, ...],
) -> str:
    need_payload: dict[str, Any] = {
        "id": information_need.id,
        "description": information_need.description,
    }
    if information_need.evidence_expectation is not None:
        need_payload["evidence_expectation"] = (
            information_need.evidence_expectation.to_dict()
        )

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
        "allowed_aspect_ids": list(allowed_aspect_ids),
        "research_question": {
            "id": research_question.id,
            "question": research_question.question,
        },
        "information_need": need_payload,
        "deterministic_facts": deterministic_facts,
        "evidence": build_evidence_payload(evidence),
    }
    return json.dumps(body, indent=2, sort_keys=True)
