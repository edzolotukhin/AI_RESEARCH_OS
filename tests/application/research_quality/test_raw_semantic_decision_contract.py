"""Tests for RawSemanticDecision structured-output contract (P1-06 M3)."""

from __future__ import annotations

import json
import unittest

from application.research_quality.raw_semantic_decision_contract import (
    DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS,
    FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS,
    evaluate_raw_semantic_decision_payload,
    raw_semantic_decision_payload_contract,
)
from domain.research_quality.semantic_decision_normalizer import LEGACY_NEED_ASPECT_ID

def _valid_payload() -> dict[str, object]:
    return {
        "supported_aspects": ["market_size_value"],
        "missing_aspects": [],
        "semantic_conflicts": [],
        "confidence": 0.9,
        "reason": "Evidence supports the required aspect.",
    }


class RawSemanticDecisionContractTests(unittest.TestCase):
    def test_valid_payload_accepted(self) -> None:
        self.assertTrue(raw_semantic_decision_payload_contract(_valid_payload()))
        self.assertIsNone(evaluate_raw_semantic_decision_payload(_valid_payload()))

    def test_forbidden_status_field_rejected(self) -> None:
        payload = {**_valid_payload(), "status": "sufficient"}
        self.assertFalse(raw_semantic_decision_payload_contract(payload))
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "forbidden_field:status",
        )

    def test_forbidden_gap_types_field_rejected(self) -> None:
        payload = {**_valid_payload(), "gap_types": ["insufficient_depth"]}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "forbidden_field:gap_types",
        )

    def test_forbidden_coverage_field_rejected(self) -> None:
        payload = {**_valid_payload(), "coverage": 1.0}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "forbidden_field:coverage",
        )

    def test_missing_supported_aspects_rejected(self) -> None:
        payload = dict(_valid_payload())
        del payload["supported_aspects"]
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "missing_field:supported_aspects",
        )

    def test_wrong_type_confidence_rejected(self) -> None:
        payload = {**_valid_payload(), "confidence": "0.9"}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "wrong_type:confidence",
        )

    def test_confidence_below_zero_rejected(self) -> None:
        payload = {**_valid_payload(), "confidence": -0.1}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "invalid_confidence_range",
        )

    def test_confidence_above_one_rejected(self) -> None:
        payload = {**_valid_payload(), "confidence": 1.5}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "invalid_confidence_range",
        )

    def test_overlap_supported_and_missing_rejected(self) -> None:
        payload = {
            **_valid_payload(),
            "supported_aspects": ["market_size_value"],
            "missing_aspects": ["market_size_value"],
        }
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "supported_missing_overlap",
        )

    def test_unresolvable_with_explicit_missing_rejected(self) -> None:
        payload = {
            **_valid_payload(),
            "supported_aspects": [],
            "missing_aspects": [LEGACY_NEED_ASPECT_ID],
            "semantic_conflicts": ["unresolvable"],
        }
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "misclassified_unresolvable",
        )

    def test_blank_reason_rejected(self) -> None:
        payload = {**_valid_payload(), "reason": "   "}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "blank_reason",
        )

    def test_long_reason_rejected(self) -> None:
        payload = {**_valid_payload(), "reason": "x" * (DEFAULT_RAW_SEMANTIC_MAX_REASON_CHARS + 1)}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "reason_too_long",
        )

    def test_invalid_aspect_entry_rejected(self) -> None:
        payload = {**_valid_payload(), "supported_aspects": [""]}
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "invalid_aspect_entry",
        )

    def test_too_many_aspect_entries_rejected(self) -> None:
        payload = {
            **_valid_payload(),
            "supported_aspects": [f"aspect-{index}" for index in range(9)],
        }
        self.assertEqual(
            evaluate_raw_semantic_decision_payload(payload),
            "array_too_long:supported_aspects",
        )

    def test_all_forbidden_fields_covered(self) -> None:
        for field in FORBIDDEN_RAW_SEMANTIC_POLICY_FIELDS:
            payload = {**_valid_payload(), field: "value"}
            self.assertEqual(
                evaluate_raw_semantic_decision_payload(payload),
                f"forbidden_field:{field}",
            )

    def test_deterministic_serialization(self) -> None:
        first = json.dumps(_valid_payload(), sort_keys=True)
        second = json.dumps(_valid_payload(), sort_keys=True)
        self.assertEqual(first, second)


class RawSemanticDecisionLegacyContractTests(unittest.TestCase):
    def test_legacy_aspect_payload_valid(self) -> None:
        payload = {
            "supported_aspects": [LEGACY_NEED_ASPECT_ID],
            "missing_aspects": [],
            "semantic_conflicts": [],
            "confidence": 0.9,
            "reason": "Supported.",
        }
        self.assertIsNone(evaluate_raw_semantic_decision_payload(payload))


if __name__ == "__main__":
    unittest.main()
