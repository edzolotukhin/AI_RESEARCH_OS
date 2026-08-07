"""P1-06 M3.4 initial prompt contract alignment tests."""

from __future__ import annotations

import unittest

from application.research_quality.raw_semantic_decision_contract import (
    FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS,
    RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
    raw_semantic_decision_output_instructions,
    raw_semantic_decision_payload_schema_text,
    render_raw_semantic_decision_output_contract,
)
from domain.research_quality.semantic_decision_normalizer import LEGACY_NEED_ASPECT_ID
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    _system_prompt,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    _build_correction_prompt,
)
from application.exceptions.structured_output_error import StructuredOutputError
from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt


class M34InitialPromptAlignmentTests(unittest.TestCase):
    def test_first_pass_prompt_includes_output_shape(self) -> None:
        prompt = _system_prompt()
        self.assertIn("OUTPUT CONTRACT (RawSemanticDecision JSON only)", prompt)
        self.assertIn(raw_semantic_decision_payload_schema_text(), prompt)

    def test_all_five_required_fields_communicated(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        for field in (
            "supported_aspects",
            "missing_aspects",
            "semantic_conflicts",
            "confidence",
            "reason",
        ):
            self.assertIn(field, instructions)

    def test_legacy_prompt_contains_exact_legacy_need_identifier(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn(LEGACY_NEED_ASPECT_ID, instructions)

    def test_legacy_supported_or_missing_not_both(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("supported OR missing, never both", instructions)

    def test_prompt_forbids_invented_legacy_aspect_ids(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("Do not invent additional aspect identifiers", instructions)

    def test_policy_fields_explicitly_forbidden(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        for field in FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS:
            self.assertIn(field, instructions)

    def test_deterministic_gap_types_input_context_only(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("deterministic_gap_types", instructions)
        self.assertIn("INPUT CONTEXT ONLY", instructions)

    def test_expectation_backed_required_aspects_rule(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn("EvidenceExpectation.required_aspects", instructions)

    def test_initial_and_correction_reference_same_schema(self) -> None:
        initial = render_raw_semantic_decision_output_contract()
        correction = _build_correction_prompt(
            original_prompt=Prompt(system=_system_prompt(), user="{}"),
            invalid_response=LLMResponse(content="{}", finish_reason="stop"),
            error=StructuredOutputError("contract failure", stage="contract"),
            payload_schema=RAW_SEMANTIC_DECISION_PAYLOAD_SCHEMA,
        )
        schema = raw_semantic_decision_payload_schema_text()
        self.assertIn(schema, initial)
        self.assertIn(schema, correction.user)

    def test_supported_missing_exclusivity_in_first_pass(self) -> None:
        instructions = raw_semantic_decision_output_instructions()
        self.assertIn(
            "MUST NOT appear in both supported_aspects and missing_aspects",
            instructions,
        )


if __name__ == "__main__":
    unittest.main()
