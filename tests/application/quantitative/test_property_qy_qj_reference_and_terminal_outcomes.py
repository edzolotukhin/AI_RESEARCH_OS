from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.insight_synthesis import QuantitativeInsightSynthesisService, QuantitativeInsightValidator
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.vertical_service import RealQuantitativeStageService
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult, QuantitativeInsightRejection
from domain.quantitative.report import QuantitativeReportCompositionResult, QuantitativeReportRejection
from domain.quantitative.workflow import QuantitativeAnalysisManifest, QuantitativeTerminalOutcome, QuantitativeTerminalResult
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import finding, result
from tests.application.quantitative.test_property_qj_quantitative_insight_synthesis import FakeInsightGenerator
from tests.application.quantitative.test_property_qx_qi_reference_and_zero_finding import _TerminalState


class _NeverReport:
    def __init__(self): self.calls = 0
    def compose(self, **_kwargs):
        self.calls += 1
        raise AssertionError("QK must be skipped")


class PropertyQYTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()

    def accepted_finding(self):
        authority = result("qy-result", "42", category="X")
        raw = replace(
            finding(QuantitativeClaimType.DESCRIPTIVE_VALUE, (authority,), value="42", statistic_type=authority.statistic_type, category="X", display_value="42.0"),
            finding_id="finding-1",
        )
        return QuantitativeFindingSupportValidator(digest_provider=self.digest).validate(
            raw, statistical_results={authority.result_id: authority}
        )

    def test_qj_resolves_bundle_fingerprint_and_ignores_model_override(self):
        accepted = self.accepted_finding()
        proposal = {
            "insight_type": "SYNTHESIS", "insight_text": "The accepted share was 42.0%.",
            "supporting_finding_ids": [accepted.finding_id],
            "supporting_finding_fingerprints": {accepted.finding_id: "forged"},
            "referenced_display_values": ["42.0"], "direction": None,
            "limitation_note": None,
        }
        generator = FakeInsightGenerator({"proposals": [proposal]})
        service = QuantitativeInsightSynthesisService(
            generator=generator,
            validator=QuantitativeInsightValidator(digest_provider=self.digest),
            digest_provider=self.digest,
        )
        generated = service.generate(findings=(accepted,))
        self.assertEqual(generated.acceptance_summary["accepted"], 1)
        self.assertEqual(
            generated.accepted_insights[0].supporting_finding_refs[0].support_validation_fingerprint,
            accepted.support_validation_fingerprint,
        )
        schema = generator.prompts[0].split("ACCEPTED_FINDINGS=", 1)[0]
        self.assertIn("supporting_finding_ids", schema)
        self.assertNotIn("supporting_finding_fingerprints", schema)

    def terminal_service(self, findings, insights, report=None, *, unweighted=False):
        service = object.__new__(RealQuantitativeStageService)
        repository = InMemoryQuantitativeStateRepository()
        durable = QuantitativeStateService(repository=repository, digest_provider=self.digest)
        dataset = SimpleNamespace(version_id="dataset-v2", parent_version_id="dataset-v1", dataset_fingerprint="dataset-fp")
        qc = SimpleNamespace(fingerprint="qc-fp")
        weights = SimpleNamespace(weight_set_id="weights-1", reproducibility_fingerprint="weights-fp")
        manifest = QuantitativeAnalysisManifest("manifest-1", "dataset-v2", ("stat-record",), (), (), "manifest-fp")
        stat = SimpleNamespace(result_id="result-1")
        objects = {
            "dataset_record_id": dataset, "qc_record_id": qc,
            "analysis_manifest_record_id": manifest,
            "finding_generation_record_id": findings,
            "insight_generation_record_id": insights,
        }
        if not unweighted:
            objects["weight_set_record_id"] = weights
        if report is not None: objects["report_composition_record_id"] = report
        service._load = lambda state, key, project_id, expected: objects[key]
        service.state = _TerminalState(durable, stat)
        service.digest = self.digest
        service.generation_mode = "production"
        service.reports = _NeverReport()
        def persist(value, kind, project_id, run_id, **kwargs):
            record_id = f"{run_id}:{kind}"
            durable.persist(value, record_id=record_id, project_id=project_id, run_id=run_id, dataset_version_id=kwargs.get("dataset_id"), accepted=kwargs.get("accepted"))
            return record_id
        service._persist = persist
        state = {key: key for key in objects}
        if unweighted:
            state.update(
                study_weighting_mode="UNWEIGHTED",
                weighting_authority_fingerprint="design-weighting-fp",
                analysis_execution_mode="DESIGN_AWARE_EXECUTION",
            )
        else:
            state["weight_approval_id"] = "weight-approval"
        return service, durable, state

    def test_zero_insights_skips_qk_and_completes_truthfully(self):
        accepted = self.accepted_finding()
        findings = QuantitativeFindingGenerationResult("fg", "bundle", "gen", "v", "p", (accepted,), (accepted,), (), {}, {"accepted": 1}, "fg-fp")
        rejection = QuantitativeInsightRejection(1, {"supporting_finding_ids": ["missing"]}, "missing", "rej-fp")
        insights = QuantitativeInsightGenerationResult("ig", "bundle", "gen", "v", "p", (), (), (rejection,), {}, {"accepted": 0, "rejected": 1}, "ig-fp")
        service, durable, state = self.terminal_service(findings, insights)
        state = service._quant_report("project", "run", {**state, "zero_supported_insights": "true"})
        self.assertEqual(service.reports.calls, 0)
        completed = service._quant_complete("project", "run", state)
        terminal = durable.load(completed["terminal_result_record_id"], project_id="project", expected_type=QuantitativeTerminalResult)
        self.assertEqual(terminal.terminal_outcome, QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_INSIGHTS)
        self.assertEqual(terminal.report_status, "NOT_GENERATED_NO_SUPPORTED_INSIGHTS")
        self.assertEqual((terminal.accepted_finding_count, terminal.accepted_insight_count), (1, 0))

    def test_rejected_report_is_controlled_terminal(self):
        accepted = self.accepted_finding()
        accepted_insight = SimpleNamespace(validation_fingerprint="insight-fp")
        findings = QuantitativeFindingGenerationResult("fg", "bundle", "gen", "v", "p", (accepted,), (accepted,), (), {}, {"accepted": 1}, "fg-fp")
        insights = QuantitativeInsightGenerationResult("ig", "bundle", "gen", "v", "p", (accepted_insight,), (accepted_insight,), (), {}, {"accepted": 1}, "ig-fp")
        rejected = QuantitativeReportRejection({"title": "unsupported"}, "unsupported support", "report-rej-fp")
        report = QuantitativeReportCompositionResult("rc", "bundle", "gen", "v", "p", None, None, (rejected,), {}, "rc-fp")
        service, durable, state = self.terminal_service(findings, insights, report)
        completed = service._quant_complete("project", "run", state)
        terminal = durable.load(completed["terminal_result_record_id"], project_id="project", expected_type=QuantitativeTerminalResult)
        self.assertEqual(terminal.terminal_outcome, QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_REPORT)
        self.assertEqual(terminal.report_status, "REJECTED_NO_SUPPORTED_REPORT")
        self.assertEqual((terminal.accepted_finding_count, terminal.accepted_insight_count), (1, 1))

    def test_unweighted_terminal_binds_explicit_authority_without_weightset(self):
        accepted = self.accepted_finding()
        findings = QuantitativeFindingGenerationResult("fg", "bundle", "gen", "v", "p", (accepted,), (accepted,), (), {}, {"accepted": 1}, "fg-fp")
        insights = QuantitativeInsightGenerationResult("ig", "bundle", "gen", "v", "p", (), (), (), {}, {"accepted": 0}, "ig-fp")
        service, durable, state = self.terminal_service(findings, insights, unweighted=True)
        state["zero_supported_insights"] = "true"
        completed = service._quant_complete("project", "run", state)
        terminal = durable.load(completed["terminal_result_record_id"], project_id="project", expected_type=QuantitativeTerminalResult)
        self.assertEqual(terminal.weighting_mode, "UNWEIGHTED")
        self.assertEqual(terminal.weighting_authority_fingerprint, "design-weighting-fp")
        self.assertIsNone(terminal.weight_set_id)
        self.assertIsNone(terminal.weight_set_fingerprint)
        self.assertIsNone(terminal.weight_approval_id)


if __name__ == "__main__":
    unittest.main()
