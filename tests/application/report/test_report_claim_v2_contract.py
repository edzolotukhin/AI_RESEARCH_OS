from __future__ import annotations

import copy
from dataclasses import fields
from types import SimpleNamespace
import unittest

from application.report.claim_contract import (
    authority_digest_v2,
    claim_digest_v2,
    component_digest_v2,
)
from domain.reports.report_claim import (
    REPORT_CLAIM_V2_VERSION,
    ClaimScope,
    NumericFact,
    ReportClaim,
    ReportClaimContractError,
)
import tests.application.report.test_report_claim_contract as v1_fixtures


class ReportClaimV2ContractTests(unittest.TestCase):
    def scope(self) -> ClaimScope:
        return ClaimScope(
            ("ukraine",), (), ("2024",), ("population",), (),
            (NumericFact("10", "persons", "absolute", ("ukraine",), ("2024",), ("population",), ()),),
        )

    def claim(self, *, reverse_maps: bool = False) -> ReportClaim:
        finding = {"finding-1": component_digest_v2({"statement": "F"})}
        insights = {"insight-1": component_digest_v2({"statement": "I", "finding_refs": ["finding-1"]})}
        evidence = {"ev-1": component_digest_v2({"statement": "E", "source_id": "source-1"})}
        sources = {"source-1": component_digest_v2({"content_revision": 1, "content_checksum": "c"})}
        proofs = {"ev-1": component_digest_v2({"period": "2024", "value": "10"})}
        if reverse_maps:
            finding, insights, evidence, sources, proofs = (
                dict(reversed(tuple(value.items()))) for value in (finding, insights, evidence, sources, proofs)
            )
        values = dict(
            claim_id="claim-1", project_id="project-1", source_workflow_run_id="source-run",
            report_workflow_run_id="report-run", design_id="design-1",
            research_question_ids=("rq-1",), information_need_ids=("in-1",),
            finding_ids=("finding-1",), insight_ids=("insight-1",), evidence_ids=("ev-1",),
            kind="observation", proposition="Population was 10.", certainty="direct",
            direction="not_applicable", scope=self.scope(), support_evidence_ids=("ev-1",),
            source_ids=("source-1",), citation_ids=("citation-1",),
            finding_content_digests=finding, insight_content_digests=insights,
            insight_finding_refs={"insight-1": ("finding-1",)},
            evidence_content_digests=evidence, source_revision_digests=sources,
            numeric_observation_proof_digests=proofs,
            status="validated", contract_version=REPORT_CLAIM_V2_VERSION,
            validated_at="2026-01-01T00:00:00Z", version=REPORT_CLAIM_V2_VERSION,
        )
        draft = SimpleNamespace(**values, authority_digest="")
        values["authority_digest"] = authority_digest_v2(draft)
        draft.authority_digest = values["authority_digest"]
        values["claim_digest"] = claim_digest_v2(draft)
        return ReportClaim(**values)

    def direct_values(self) -> dict:
        claim = self.claim()
        return {item.name: getattr(claim, item.name) for item in fields(ReportClaim)}

    def assert_direct_scalar_rejected(self, name: str, value) -> None:
        values = self.direct_values()
        values[name] = value
        draft = SimpleNamespace(**values)
        if name not in {"authority_digest", "claim_digest"}:
            values["authority_digest"] = authority_digest_v2(draft)
            draft.authority_digest = values["authority_digest"]
        if name != "claim_digest":
            values["claim_digest"] = claim_digest_v2(draft)
        with self.assertRaises(ReportClaimContractError):
            ReportClaim(**values)

    def assert_payload_rejected(self, mutate) -> None:
        payload = copy.deepcopy(self.claim().to_dict())
        mutate(payload)
        with self.assertRaises(ReportClaimContractError):
            ReportClaim.from_dict(payload)

    def test_v1_round_trip_serialization_is_unchanged(self) -> None:
        legacy = v1_fixtures.ReportClaimContractTests()
        legacy.setUp()
        claim = legacy.claim()
        payload = claim.to_dict()
        self.assertNotIn("claim_digest", payload["validation"])
        self.assertNotIn("source_revision_digests", payload["support"])
        self.assertEqual(ReportClaim.from_dict(payload).to_dict(), payload)

    def test_v2_canonical_round_trip(self) -> None:
        claim = self.claim()
        self.assertEqual(ReportClaim.from_dict(claim.to_dict()), claim)

    def test_valid_v2_direct_construction_remains_supported(self) -> None:
        self.assertEqual(self.claim().version, REPORT_CLAIM_V2_VERSION)

    def test_direct_constructor_rejects_nonstring_v2_scalars(self) -> None:
        names = (
            "claim_id", "project_id", "source_workflow_run_id", "report_workflow_run_id",
            "design_id", "kind", "proposition", "certainty", "direction", "status",
            "contract_version", "version", "authority_digest", "claim_digest", "validated_at",
        )
        for name in names:
            for value in (1, True, None):
                with self.subTest(name=name, value=value):
                    self.assert_direct_scalar_rejected(name, value)

    def test_reordered_maps_have_identical_digests(self) -> None:
        first, second = self.claim(), self.claim(reverse_maps=True)
        self.assertEqual(first.authority_digest, second.authority_digest)
        self.assertEqual(first.claim_digest, second.claim_digest)

    def test_tampered_proposition_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["assertion"].update(proposition="tampered"))

    def test_tampered_insight_digest_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["support"]["insight_content_digests"].update({"insight-1": "0" * 64}))

    def test_tampered_source_revision_digest_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["support"]["source_revision_digests"].update({"source-1": "0" * 64}))

    def test_tampered_numeric_proof_digest_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["support"]["numeric_observation_proof_digests"].update({"ev-1": "0" * 64}))

    def test_missing_required_support_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["support"].pop("source_revision_digests"))

    def test_mismatched_id_digest_maps_are_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["support"]["source_revision_digests"].update({"source-2": "0" * 64}))

    def test_malformed_contract_version_is_rejected(self) -> None:
        self.assert_payload_rejected(lambda value: value["validation"].update(contract_version="desk_report_claim_v1"))

    def test_duplicate_top_level_and_support_ids_are_rejected(self) -> None:
        mutations = (
            lambda value: value["finding_ids"].append("finding-1"),
            lambda value: value["evidence_ids"].append("ev-1"),
            lambda value: value["insight_ids"].append("insight-1"),
            lambda value: value["support"]["source_ids"].append("source-1"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_payload_rejected(mutate)

    def test_duplicate_nested_insight_finding_refs_are_rejected(self) -> None:
        self.assert_payload_rejected(
            lambda value: value["support"]["insight_finding_refs"]["insight-1"].append("finding-1"),
        )

    def test_nonstring_ids_are_rejected_without_coercion(self) -> None:
        mutations = (
            lambda value: value["finding_ids"].__setitem__(0, 1),
            lambda value: value["evidence_ids"].__setitem__(0, True),
            lambda value: value["insight_ids"].__setitem__(0, None),
            lambda value: value.update(claim_id=1),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_payload_rejected(mutate)

    def test_nonstring_digest_keys_and_values_are_rejected(self) -> None:
        def numeric_key(value) -> None:
            digest = value["support"]["source_revision_digests"].pop("source-1")
            value["support"]["source_revision_digests"][1] = digest

        mutations = (
            numeric_key,
            lambda value: value["support"]["finding_content_digests"].update({"finding-1": 1}),
            lambda value: value["support"]["evidence_content_digests"].update({"ev-1": None}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_payload_rejected(mutate)

    def test_nonstring_nested_reference_elements_are_rejected(self) -> None:
        for item in (1, True, None, [], {}):
            with self.subTest(item=item):
                self.assert_payload_rejected(
                    lambda value, item=item: value["support"]["insight_finding_refs"]["insight-1"].__setitem__(0, item),
                )

    def test_previously_coercible_or_normalized_key_collisions_are_rejected(self) -> None:
        def coercible_collision(value) -> None:
            digest = value["support"]["source_revision_digests"]["source-1"]
            value["support"]["source_revision_digests"][1] = digest
            value["support"]["source_revision_digests"]["1"] = digest

        def normalized_collision(value) -> None:
            digest = value["support"]["source_revision_digests"]["source-1"]
            value["support"]["source_revision_digests"][" source-1 "] = digest

        for mutate in (coercible_collision, normalized_collision):
            with self.subTest(mutate=mutate):
                self.assert_payload_rejected(mutate)


if __name__ == "__main__":
    unittest.main()
