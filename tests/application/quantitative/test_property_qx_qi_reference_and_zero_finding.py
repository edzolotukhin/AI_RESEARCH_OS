from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from application.quantitative.finding_generation import QuantitativeFindingGenerationService
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.vertical_service import RealQuantitativeStageService
from domain.quantitative.finding import (
    QuantitativeFindingGenerationResult,
    QuantitativeFindingRejection,
    QuantitativeResultReference,
)
from domain.quantitative.workflow import (
    QuantitativeAnalysisManifest,
    QuantitativeTerminalOutcome,
    QuantitativeTerminalResult,
)
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)
from application.quantitative.state_persistence import QuantitativeStateService
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qh_quantitative_finding_support_contract import (
    comparison,
    result,
)
from tests.application.quantitative.test_property_qi_llm_assisted_finding_generation import (
    FakeProposalGenerator,
    proposal,
)


class _NeverGenerator:
    def __init__(self):
        self.calls = 0

    def generate(self, **_kwargs):
        self.calls += 1
        raise AssertionError("downstream generator must be skipped")


class _TerminalState:
    def __init__(self, delegate, statistical_result):
        self._delegate = delegate
        self._statistical_result = statistical_result

    def load(self, record_id, **kwargs):
        if record_id == "stat-record":
            return self._statistical_result
        return self._delegate.load(record_id, **kwargs)

    def persist(self, value, **kwargs):
        return self._delegate.persist(value, **kwargs)


class PropertyQXTests(unittest.TestCase):
    def setUp(self):
        self.digest = Sha256DigestProvider()

    def service(self, proposals):
        generator = FakeProposalGenerator({"proposals": proposals}, identity="qx-fake-v1")
        return QuantitativeFindingGenerationService(
            generator=generator,
            support_validator=QuantitativeFindingSupportValidator(
                digest_provider=self.digest
            ),
            digest_provider=self.digest,
        ), generator

    def test_claim_cardinality_and_bundle_resolved_fingerprints(self):
        percentage = result("percentage", "42")
        mean = result("mean", "7.4", statistic_type="NUMERIC_MEAN", category=None)
        nps = result("nps", "36", statistic_type="NPS", category=None)
        a = result(
            "a", "70", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="A"
        )
        b = result(
            "b", "40", statistic_type="CROSS_TAB_COLUMN_PERCENTAGE", column="B"
        )
        qg = comparison(a, b)
        proposals = (
            proposal(percentage, "DESCRIPTIVE_VALUE"),
            proposal(mean, "NUMERIC_SUMMARY"),
            proposal(nps, "KPI_VALUE"),
            proposal(
                a, "DESCRIPTIVE_COMPARISON", refs=[a.result_id, b.result_id],
                value="30", direction="HIGHER", category="X", display=None,
            ),
            proposal(
                a, "SIGNIFICANT_COMPARISON", refs=[a.result_id, b.result_id],
                comparisons=[qg.comparison_result_id], value="30",
                direction="HIGHER", category="X", display=None,
            ),
        )
        generated = self.service(list(proposals))[0].generate(
            statistical_results=(percentage, mean, nps, a, b),
            comparison_results=(qg,),
        )
        self.assertEqual(generated.acceptance_summary["accepted"], 5)
        expected = {
            "DESCRIPTIVE_VALUE": (1, 0),
            "NUMERIC_SUMMARY": (1, 0),
            "KPI_VALUE": (1, 0),
            "DESCRIPTIVE_COMPARISON": (2, 0),
            "SIGNIFICANT_COMPARISON": (2, 1),
        }
        for finding in generated.accepted_findings:
            self.assertEqual(
                (len(finding.statistical_result_refs), len(finding.comparison_result_refs)),
                expected[finding.claim.claim_type.value],
            )
        self.assertEqual(
            generated.accepted_findings[0].statistical_result_refs[0].reproducibility_fingerprint,
            percentage.reproducibility_fingerprint,
        )

    def test_unknown_duplicate_and_invalid_cardinality_fail_closed(self):
        authority = result("percentage", "42")
        invalid = [
            proposal(authority, "DESCRIPTIVE_VALUE", refs=["unknown"]),
            proposal(authority, "DESCRIPTIVE_VALUE", refs=[authority.result_id, authority.result_id]),
            proposal(authority, "DESCRIPTIVE_VALUE", refs=[authority.result_id, "other"]),
            proposal(authority, "DESCRIPTIVE_COMPARISON", refs=[authority.result_id]),
        ]
        generated = self.service(invalid)[0].generate(statistical_results=(authority,))
        self.assertEqual(generated.acceptance_summary, {
            "proposed": 4, "parsed": 0, "accepted": 0, "rejected": 4,
        })
        reasons = " ".join(item.reason for item in generated.rejected_findings)
        self.assertIn("outside the authoritative bundle", reasons)
        self.assertIn("duplicates", reasons)
        self.assertIn("requires exactly", reasons)

    def test_model_fingerprint_fields_cannot_override_authority_or_identity(self):
        authority = result("percentage", "42")
        clean = proposal(authority, "DESCRIPTIVE_VALUE")
        forged = dict(
            clean,
            statistical_result_fingerprints={authority.result_id: "forged"},
            comparison_result_fingerprints={"anything": "forged"},
        )
        clean_result = self.service([clean])[0].generate(statistical_results=(authority,))
        forged_result = self.service([forged])[0].generate(statistical_results=(authority,))
        self.assertEqual(clean_result.accepted_findings, forged_result.accepted_findings)
        self.assertEqual(
            forged_result.accepted_findings[0].statistical_result_refs[0].reproducibility_fingerprint,
            authority.reproducibility_fingerprint,
        )

    def test_stale_reference_protection_remains_qh_authority(self):
        authority = result("percentage", "42")
        generated = self.service([proposal(authority, "DESCRIPTIVE_VALUE")])[0].generate(
            statistical_results=(authority,)
        )
        finding = generated.accepted_findings[0]
        stale = replace(
            finding,
            statistical_result_refs=(
                QuantitativeResultReference(authority.result_id, "stale-fingerprint"),
            ),
        )
        with self.assertRaisesRegex(Exception, "stale or altered"):
            QuantitativeFindingSupportValidator(digest_provider=self.digest).validate(
                stale, statistical_results={authority.result_id: authority}
            )

    def test_prompt_schema_is_ids_only_and_cardinality_aligned(self):
        authority = result("percentage", "42")
        service, generator = self.service([proposal(authority, "DESCRIPTIVE_VALUE")])
        service.generate(statistical_results=(authority,))
        prompt = generator.prompts[0]
        self.assertIn('"reference_contract"', prompt)
        self.assertIn(
            '"DESCRIPTIVE_COMPARISON":{"selected_comparison_ids":0,"selected_result_ids":2}',
            prompt,
        )
        schema = prompt.split("AUTHORITATIVE_BUNDLE=", 1)[0]
        self.assertNotIn("statistical_result_fingerprints", schema)
        self.assertNotIn("comparison_result_fingerprints", schema)
        self.assertNotIn('"value":"exact decimal or null"', schema)
        self.assertNotIn('"statistic_type":"type"', schema)
        self.assertIn("never copy, reconstruct, abbreviate", prompt)
        self.assertEqual(len(generator.prompts), 1)

    def test_zero_findings_skip_qj_qk_and_persist_truthful_terminal(self):
        rejection = QuantitativeFindingRejection(1, {"result_id": "unknown"}, "unknown", "rej-fp")
        findings = QuantitativeFindingGenerationResult(
            generation_id="generation-1", input_result_bundle_fingerprint="bundle-fp",
            generator_identity="qx-fake-v1", prompt_version="QI_FINDING_GENERATION_V2",
            prompt_fingerprint="prompt-fp", proposed_findings=(), accepted_findings=(),
            rejected_findings=(rejection,), generation_metadata={"generation_passes": 1},
            acceptance_summary={"proposed": 1, "parsed": 0, "accepted": 0, "rejected": 1},
            generation_fingerprint="generation-fp",
        )
        service = object.__new__(RealQuantitativeStageService)
        service.insights = _NeverGenerator()
        service.reports = _NeverGenerator()
        objects = {"finding_generation_record_id": findings}
        service._load = lambda state, key, project_id, expected: objects[key]
        state = {"finding_generation_record_id": "finding-record"}
        state = service._quant_insights("project", "run", state)
        state = service._quant_report("project", "run", state)
        self.assertEqual(service.insights.calls, 0)
        self.assertEqual(service.reports.calls, 0)
        self.assertEqual(state["insight_generation_status"], "SKIPPED_NO_SUPPORTED_FINDINGS")
        self.assertEqual(state["report_composition_status"], "SKIPPED_NO_SUPPORTED_FINDINGS")

        dataset = SimpleNamespace(
            version_id="dataset-v2", parent_version_id="dataset-v1",
            dataset_fingerprint="dataset-fp",
        )
        qc = SimpleNamespace(fingerprint="qc-fp")
        weights = SimpleNamespace(weight_set_id="weights-1", reproducibility_fingerprint="weights-fp")
        manifest = QuantitativeAnalysisManifest(
            "manifest-1", "dataset-v2", ("stat-record",), (), (), "manifest-fp"
        )
        stat = SimpleNamespace(result_id="result-1")
        objects.update(
            dataset_record_id=dataset, qc_record_id=qc, weight_set_record_id=weights,
            analysis_manifest_record_id=manifest,
        )
        repository = InMemoryQuantitativeStateRepository()
        durable = QuantitativeStateService(repository=repository, digest_provider=self.digest)
        service.state = _TerminalState(durable, stat)
        service.digest = self.digest
        service.generation_mode = "production"
        def persist(value, kind, project_id, run_id, **kwargs):
            record_id = f"{run_id}:{kind}"
            durable.persist(
                value, record_id=record_id, project_id=project_id,
                run_id=run_id, dataset_version_id=kwargs.get("dataset_id"),
                accepted=kwargs.get("accepted"),
            )
            return record_id
        service._persist = persist
        state.update({
            "dataset_record_id": "dataset-record", "qc_record_id": "qc-record",
            "weight_set_record_id": "weight-record",
            "analysis_manifest_record_id": "manifest-record",
            "weight_approval_id": "weight-approval",
        })
        completed = service._quant_complete("project", "run", state)
        terminal = durable.load(
            completed["terminal_result_record_id"], project_id="project",
            expected_type=QuantitativeTerminalResult,
        )
        self.assertEqual(
            terminal.terminal_outcome,
            QuantitativeTerminalOutcome.COMPLETED_WITH_NO_SUPPORTED_FINDINGS,
        )
        self.assertEqual((terminal.accepted_finding_count, terminal.rejected_finding_count), (0, 1))
        self.assertEqual(terminal.report_status, "NOT_GENERATED_NO_SUPPORTED_FINDINGS")
        self.assertEqual(completed["terminal_authority_status"], "COMPLETE_WITH_NO_SUPPORTED_FINDINGS")


if __name__ == "__main__":
    unittest.main()
