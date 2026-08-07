"""Tests for RawSemanticDecision structured-output contract (P1-06 M3)."""

from __future__ import annotations

import json
import unittest

from application.research_quality.raw_semantic_decision_contract import (
    raw_semantic_decision_payload_contract,
)


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

    def test_forbidden_status_field_rejected(self) -> None:
        payload = {**_valid_payload(), "status": "sufficient"}
        self.assertFalse(raw_semantic_decision_payload_contract(payload))

    def test_forbidden_gap_types_field_rejected(self) -> None:
        payload = {**_valid_payload(), "gap_types": ["insufficient_depth"]}
        self.assertFalse(raw_semantic_decision_payload_contract(payload))

    def test_overlap_supported_and_missing_rejected(self) -> None:
        payload = {
            **_valid_payload(),
            "supported_aspects": ["market_size_value"],
            "missing_aspects": ["market_size_value"],
        }
        self.assertFalse(raw_semantic_decision_payload_contract(payload))

    def test_invalid_confidence_rejected(self) -> None:
        payload = {**_valid_payload(), "confidence": 1.5}
        self.assertFalse(raw_semantic_decision_payload_contract(payload))

    def test_blank_reason_rejected(self) -> None:
        payload = {**_valid_payload(), "reason": "   "}
        self.assertFalse(raw_semantic_decision_payload_contract(payload))

    def test_deterministic_serialization(self) -> None:
        first = json.dumps(_valid_payload(), sort_keys=True)
        second = json.dumps(_valid_payload(), sort_keys=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
