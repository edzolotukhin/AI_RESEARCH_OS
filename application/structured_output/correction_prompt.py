from __future__ import annotations

from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.planner_bounds import PlannerBounds

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt

RESEARCH_DESIGN_PAYLOAD_SCHEMA = """
{
  "research_questions": [
    {
      "id": "string",
      "question": "string",
      "objective_refs": ["string"],
      "priority": 1,
      "rationale": "string"
    }
  ],
  "information_needs": [
    {
      "id": "string",
      "research_question_id": "string",
      "description": "string",
      "priority": 1,
      "preferred_source_types": ["string"],
      "timeframe": "string",
      "geography": "string",
      "evidence_expectation": {
        "nature": "quantitative|qualitative|mixed",
        "required_aspects": ["string"],
        "geography": "string",
        "timeframe": "string",
        "minimum_independent_sources": 1,
        "requires_quantitative_evidence": false
      }
    }
  ],
  "source_strategy": ["string"],
  "analysis_plan": ["string"],
  "deliverable_plan": ["string"],
  "assumptions": ["string"],
  "limitations": ["string"],
  "language": "string"
}
""".strip()

PLANNER_PAYLOAD_SCHEMA = RESEARCH_DESIGN_PAYLOAD_SCHEMA

_INVALID_RESPONSE_PREVIEW_LIMIT = 800


class StructuredOutputCorrectionPromptBuilder:
    """
    Builds correction prompts for structured-output retry attempts.
    """

    def build(
        self,
        *,
        original_prompt: Prompt,
        invalid_response: LLMResponse,
        error: StructuredOutputError,
        payload_schema: str,
        truncated: bool,
        allowed_executor_ids: tuple[str, ...] | None = None,
        contract_validation_message: str = "",
        planner_bounds: PlannerBounds | None = None,
    ) -> Prompt:
        bounds = planner_bounds or PlannerBounds.from_env()
        validation_summary = self._build_validation_summary(
            error,
            contract_validation_message=contract_validation_message,
        )
        invalid_preview = self._safe_response_preview(
            invalid_response.content,
        )

        if truncated:
            correction_requirements = self._truncated_requirements(bounds)
        else:
            correction_requirements = self._standard_requirements(bounds)

        sections = [
            original_prompt.user,
            "CORRECTION REQUEST",
            correction_requirements,
            "PLANNER OUTPUT LIMITS",
            bounds.format_for_prompt(),
            bounds.format_compact_instruction(),
            "VALIDATION ERROR",
            validation_summary,
            "EXPECTED PAYLOAD CONTRACT",
            payload_schema.strip(),
        ]

        if allowed_executor_ids:
            sections.extend(
                [
                    "ALLOWED EXECUTOR IDS",
                    ", ".join(allowed_executor_ids),
                    "Every task executor_id must exactly match one allowed ID.",
                ]
            )

        sections.extend(
            [
                "PREVIOUS INVALID RESPONSE",
                invalid_preview,
                "Return only one corrected JSON object.",
            ]
        )

        user_prompt = "\n\n".join(sections)

        system_prompt = "\n\n".join(
            [
                original_prompt.system,
                "When correcting a previous invalid response:",
                "- Return only one JSON object.",
                "- Do not use markdown or code fences.",
                "- Do not add explanations.",
                "- Follow the payload contract exactly.",
            ]
        )

        return Prompt(
            system=system_prompt,
            user=user_prompt,
        )

    def build_objective_coverage_correction(
        self,
        *,
        original_prompt: Prompt,
        brief,
        failure,
        previous_design_json: str,
        planner_bounds: PlannerBounds | None = None,
        payload_schema: str = RESEARCH_DESIGN_PAYLOAD_SCHEMA,
    ) -> Prompt:
        bounds = planner_bounds or PlannerBounds.from_env()
        sections = [
            original_prompt.user,
            "OBJECTIVE COVERAGE CORRECTION",
            "\n".join(
                [
                    "The previous ResearchDesign JSON is syntactically valid but fails "
                    "brief objective coverage validation.",
                    "Repair objective_refs while staying within planner output limits.",
                    "Use exact brief objective text verbatim in every objective_refs entry.",
                    "Do not invent objectives that are not listed in the brief.",
                    "Consolidate overlapping objectives into shared research questions "
                    "with multiple objective_refs when needed.",
                    bounds.format_compact_instruction(),
                    "Return JSON only.",
                ]
            ),
            "PLANNER OUTPUT LIMITS",
            bounds.format_for_prompt(),
        ]

        if failure.uncovered_objectives:
            sections.extend(
                [
                    "UNCOVERED BRIEF OBJECTIVES",
                    "Each objective below must appear verbatim in at least one "
                    "research_questions[].objective_refs array:",
                    *[f"- {objective}" for objective in failure.uncovered_objectives],
                ]
            )

        if failure.invalid_objective_refs:
            invalid_lines = [
                f"- question {question_id}: remove or replace {ref!r}"
                for question_id, ref in failure.invalid_objective_refs
            ]
            sections.extend(
                [
                    "INVALID OBJECTIVE REFS",
                    "These objective_refs do not match any brief objective:",
                    *invalid_lines,
                    "Replace each invalid ref with exact brief objective text or remove it.",
                ]
            )

        if brief.objectives:
            sections.extend(
                [
                    "CANONICAL BRIEF OBJECTIVES",
                    "objective_refs must cite these exact strings only:",
                    *[f"- {objective}" for objective in brief.objectives],
                ]
            )

        sections.extend(
            [
                "EXPECTED PAYLOAD CONTRACT",
                payload_schema.strip(),
                "PREVIOUS RESEARCH DESIGN JSON",
                self._safe_response_preview(previous_design_json),
                "Return only one corrected JSON object.",
            ]
        )

        return Prompt(
            system="\n\n".join(
                [
                    original_prompt.system,
                    "When correcting objective coverage:",
                    "- Return only one JSON object.",
                    "- Cover every brief objective exactly once across objective_refs.",
                    "- Do not use markdown or code fences.",
                ]
            ),
            user="\n\n".join(sections),
        )

    @staticmethod
    def _truncated_requirements(bounds: PlannerBounds) -> str:
        return "\n".join(
            [
                "The previous response exceeded the output token budget and was truncated.",
                "Regenerate a complete compact JSON object from the beginning.",
                "Reduce count and verbosity to satisfy the planner output limits below.",
                bounds.format_compact_instruction(),
                "Merge overlapping objectives into fewer research questions with multiple objective_refs.",
                "Keep metadata as an empty object unless strictly required.",
                "Return JSON only.",
            ]
        )

    @staticmethod
    def _standard_requirements(bounds: PlannerBounds) -> str:
        return "\n".join(
            [
                "Fix the previous invalid response.",
                "Return only one JSON object.",
                "Do not use markdown, code fences, or explanations.",
                "Follow the payload contract and planner output limits exactly.",
                bounds.format_compact_instruction(),
                "Preserve the intended plan meaning unless required to satisfy the contract.",
            ]
        )

    @staticmethod
    def _build_validation_summary(
        error: StructuredOutputError,
        *,
        contract_validation_message: str = "",
    ) -> str:
        parts = [
            f"stage={error.stage}",
            f"candidates={error.candidate_count}",
            f"syntax_valid={error.syntax_valid_count}",
            f"contract_valid={error.contract_valid_count}",
        ]

        if contract_validation_message:
            parts.append(f"details={contract_validation_message}")

        if error.is_truncated:
            parts.append("truncated=true")

        if error.finish_reason:
            parts.append(f"finish_reason={error.finish_reason}")

        if error.json_decode_message:
            parts.append(f"json_error={error.json_decode_message}")

        if error.json_error_line is not None:
            parts.append(f"line={error.json_error_line}")

        if error.json_error_column is not None:
            parts.append(f"column={error.json_error_column}")

        if error.candidate_length:
            parts.append(f"candidate_length={error.candidate_length}")

        return ", ".join(parts)

    @staticmethod
    def _safe_response_preview(
        text: str,
        limit: int = _INVALID_RESPONSE_PREVIEW_LIMIT,
    ) -> str:
        compact = text.strip()

        if len(compact) <= limit:
            return compact

        head = compact[: limit // 2]
        tail = compact[-(limit // 2) :]

        return f"{head}\n...[truncated for correction prompt]...\n{tail}"
