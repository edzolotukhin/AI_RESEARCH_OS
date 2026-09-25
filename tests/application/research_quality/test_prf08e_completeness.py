"""Offline PRF-08E integrity regressions; all inputs are synthetic."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

from application.evidence.evidence_extractor_response_shape import consume_response_shape
from application.evidence.exceptions import EvidenceResponseOutcomeError
from application.evidence.temporal_scope import qualifying_evidence, temporal_eligibility
from application.planner.research_design_payload_contract import ResearchDesignPayloadContract
from application.research.design_validator import validate_research_design
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment, build_research_readiness_result,
)
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.research_quality.deterministic_sufficiency_evaluator import (
    DeterministicSufficiencyEvaluator,
)
from application.research_quality.research_readiness_gate import ResearchReadinessGate
from domain.ai.llm_response import LLMResponse
from domain.common.exceptions import ValidationError
from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.research_brief import ResearchBrief
from domain.research_quality.research_readiness_assessment import ResearchReadinessAssessment
from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
from tests.infrastructure.evidence.test_p1_07_6_c_evidence_completion_classification_offline_acceptance import (
    VALID_ITEM, _design as extraction_design, _run_context, _source,
)


def _brief() -> ResearchBrief:
    return ResearchBrief(title="Synthetic UK charging", business_question="What is comparable?",
                         timeframe="1 January 2025 to 1 July 2026", geography=("UK",))


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="synthetic-design",
        research_questions=(
            ResearchQuestion(id="RQ1", question="What did the measurements show?"),
            ResearchQuestion(id="RQ2", question="Which category rules apply?"),
        ),
        information_needs=(
            InformationNeed(id="IN1", research_question_id="RQ1", description="Device counts",
                            evidence_expectation=EvidenceExpectation(
                                nature=EvidenceNature.QUANTITATIVE,
                                required_aspects=("device_counts",),
                            )),
            InformationNeed(id="IN2", research_question_id="RQ2",
                            description="Definitions, methodology and classification rules",
                            evidence_expectation=EvidenceExpectation(
                                nature=EvidenceNature.QUALITATIVE,
                                required_aspects=("category_rules",),
                            )),
        ),
        source_strategy=("Official sources",), analysis_plan=("Compare",),
        deliverable_plan=("Summary",),
    )


def _evidence(identity: str, need: str, statement: str, excerpt: str,
              period: str | None = None) -> Evidence:
    return Evidence(
        id=identity, project_id="synthetic", source_id="same-source",
        source_content_checksum="synthetic", workflow_run_id="synthetic-run",
        research_design_id="synthetic-design", statement=statement,
        source_excerpt=excerpt, created_at="2026-09-25T00:00:00Z",
        research_question_refs=("RQ1" if need == "IN1" else "RQ2",),
        information_need_refs=(need,),
        metadata={"observation_period": period} if period else {},
    )


class DesignCoverageTests(unittest.TestCase):
    def test_uncovered_question_rejected_by_generation_contract_and_validator(self):
        malformed = replace(_design(), information_needs=_design().information_needs[:1])
        contract = ResearchDesignPayloadContract()
        self.assertFalse(contract.accepts(malformed.to_dict()))
        self.assertIn("RQ2", contract.last_validation_error)
        with self.assertRaisesRegex(ValidationError, "RQ2"):
            validate_research_design(malformed)
        validate_research_design(_design())

    def test_empty_need_aggregation_never_becomes_ready(self):
        empty = build_research_readiness_assessment(
            research_question_id="RQ2", need_assessments=(),
        )
        self.assertFalse(empty.ready_for_analysis)
        self.assertIn("no information needs", empty.reason)
        result = build_research_readiness_result((empty,))
        self.assertFalse(result.ready_for_analysis)
        self.assertEqual(result.blocking_research_question_ids, ("RQ2",))
        with self.assertRaises(ValidationError):
            ResearchReadinessAssessment(
                research_question_id="RQ2", information_need_assessments=(),
                ready_for_analysis=True,
            )

    def test_immutable_legacy_snapshot_remains_readable(self):
        old = ResearchReadinessAssessment.from_dict({
            "research_question_id": "RQ5", "information_need_assessments": [],
            "ready_for_analysis": True, "reason": "All information needs sufficient.",
        })
        self.assertTrue(old.ready_for_analysis)
        self.assertEqual(old.to_dict()["information_need_assessments"], [])


class ClaimTemporalTests(unittest.TestCase):
    def setUp(self):
        self.design = _design()
        self.cutoff = date(2026, 7, 1)

    def test_measurement_date_states(self):
        need = self.design.information_needs[0]
        cases = (
            ("June 2026", "applicable_satisfied"),
            ("August 2026", "applicable_failed"),
            (None, "applicable_unresolved"),
        )
        for period, expected in cases:
            with self.subTest(period=period):
                item = _evidence("count", "IN1", "There were 100 devices",
                                 f"There were 100 devices in {period or 'the period'}.", period)
                self.assertEqual(temporal_eligibility(item, need, self.cutoff), expected)

    def test_undated_definition_and_methodology_are_claim_specific(self):
        need = self.design.information_needs[1]
        definition = _evidence("definition", "IN2", "A connector is defined as an outlet",
                               "A connector is defined as an outlet on a device.")
        method = _evidence("method", "IN2", "Methodology for category assignment",
                           "Methodology for category assignment uses site location.")
        count = _evidence("count", "IN2", "There were 10,000 rapid chargers",
                          "There were 10,000 rapid chargers in August 2026.", "August 2026")
        for item in (definition, method):
            self.assertEqual(temporal_eligibility(item, need, self.cutoff), "not_applicable")
        self.assertEqual(temporal_eligibility(count, need, self.cutoff), "applicable_failed")
        qualified = qualifying_evidence(design=self.design,
                                        evidence=(definition, method, count), brief=_brief())
        self.assertEqual({item.id for item in qualified}, {"definition", "method"})

    def test_page_label_cannot_make_an_undated_statistic_eligible(self):
        need = self.design.information_needs[1]
        statistic = _evidence("stat", "IN2", "Definition: total count was 10,000 devices",
                              "Definition page: total count was 10,000 devices.")
        self.assertEqual(temporal_eligibility(statistic, need, self.cutoff),
                         "applicable_unresolved")


class ExtractionRecoveryTests(unittest.TestCase):
    def _extract(self, responses):
        client = Mock()
        client.generate.side_effect = responses
        extractor = LlmEvidenceExtractor(llm_client=client)
        try:
            result = extractor.extract(source=_source(), design=extraction_design("IN1"),
                                       run_context=_run_context("IN1"))
            error = None
        except EvidenceResponseOutcomeError as exc:
            result, error = [], exc
        return result, error, client, consume_response_shape()

    def test_valid_response_uses_one_attempt(self):
        result, error, client, shape = self._extract([
            LLMResponse(content=json.dumps({"items": [VALID_ITEM]})),
        ])
        self.assertIsNone(error)
        self.assertEqual(len(result), 1)
        self.assertEqual(client.generate.call_count, 1)
        self.assertEqual(shape.structured_attempts, 1)

    def test_invalid_then_valid_is_accepted_once_with_feedback(self):
        result, error, client, shape = self._extract([
            LLMResponse(content='{"items":[{"statement":"broken"'),
            LLMResponse(content=json.dumps({"items": [VALID_ITEM]})),
        ])
        self.assertIsNone(error)
        self.assertEqual(len(result), 1)
        self.assertEqual(client.generate.call_count, 2)
        self.assertEqual(shape.structured_attempts, 2)
        self.assertIn("invalid_json", client.generate.call_args.args[0].user)

    def test_two_invalid_responses_fail_typed_and_bounded(self):
        result, error, client, shape = self._extract([
            LLMResponse(content="{"), LLMResponse(content="{"),
        ])
        self.assertEqual(result, [])
        self.assertEqual(error.classification, "invalid_json")
        self.assertEqual(client.generate.call_count, 2)
        self.assertEqual(shape.structured_attempts, 2)

    def test_schema_mismatch_cannot_become_evidence(self):
        result, error, client, _ = self._extract([
            LLMResponse(content='{"items":"not an array"}'),
            LLMResponse(content='{"items":"not an array"}'),
        ])
        self.assertEqual(result, [])
        self.assertEqual(error.classification, "schema_contract_mismatch")
        self.assertEqual(client.generate.call_count, 2)

    def test_type_invalid_item_cannot_be_coerced_into_evidence(self):
        invalid = dict(VALID_ITEM, statement=123, direct="false")
        result, error, client, shape = self._extract([
            LLMResponse(content=json.dumps({"items": [invalid, VALID_ITEM]})),
        ])
        self.assertEqual(result, [])
        self.assertEqual(error.classification, "schema_contract_mismatch")
        self.assertEqual(shape.rejected_schema_invalid_item, 1)
        self.assertEqual(client.generate.call_count, 1)


class Prf08dPatternTests(unittest.TestCase):
    def test_combined_failure_shape_remains_insufficient(self):
        design = _design()
        uncovered = replace(design, research_questions=(*design.research_questions,
            ResearchQuestion(id="RQ5", question="Which conclusions are unsupported?")))
        with self.assertRaisesRegex(ValidationError, "RQ5"):
            validate_research_design(uncovered)
        self.assertFalse(build_research_readiness_assessment(
            research_question_id="RQ5", need_assessments=(),
        ).ready_for_analysis)
        definition = _evidence("def-1", "IN2", "A connector is defined as an outlet",
                               "A connector is defined as an outlet on a device.")
        dependent = replace(definition, id="def-2", source_id="second-source")
        for item in (definition, dependent):
            item.metadata["data_lineage"] = {
                "status": "established", "origin_id": "synthetic-shared-feed",
            }
        later = _evidence("later", "IN1", "There were 100 devices",
                          "There were 100 devices in August 2026.", "August 2026")
        eligible = qualifying_evidence(design=design,
                                        evidence=(definition, dependent, later), brief=_brief())
        self.assertEqual({item.id for item in eligible}, {"def-1", "def-2"})
        signals = DeterministicSufficiencyEvaluator().evaluate(
            design=design, evidence=eligible,
        )
        self.assertEqual(signals[1].independent_source_count, 1)
        self.assertEqual(signals[0].evidence_count, 0)
        result, error, client, _ = ExtractionRecoveryTests()._extract([
            LLMResponse(content="{"), LLMResponse(content="{"),
        ])
        self.assertEqual(result, [])
        self.assertEqual(error.classification, "invalid_json")
        self.assertEqual(client.generate.call_count, 2)
        readiness = DeterministicResearchSufficiencyEvaluator().evaluate(
            design=design, evidence=eligible,
        )
        self.assertFalse(readiness.ready_for_analysis)
        self.assertEqual(ResearchReadinessGate().research_outcome(readiness).value,
                         "insufficient_research")


if __name__ == "__main__":
    unittest.main()
