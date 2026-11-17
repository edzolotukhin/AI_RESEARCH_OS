from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from decimal import Decimal
import unittest

from application.report.claim_contract import authority_digest_v2, claim_digest_v2
from application.report.claim_lineage_v2 import build_claim_lineage_v2
from application.report.claim_revision_v2 import ClaimRevisionV2Context, ClaimRevisionV2Error, VerifiedV2RevisionInput, rebuild_report_claim_v2
from domain.reports.report_claim import ClaimScope, NumericFact, ReportClaim
from tests.application.report.test_claim_lineage_v2 import ClaimLineageV2Tests
from tests.application.report.test_report_claim_v2_contract import ReportClaimV2ContractTests


class ClaimRevisionV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        base = ClaimLineageV2Tests()
        base.setUp()
        self.base = base
        material = base.build()
        fixture = ReportClaimV2ContractTests()
        fixture.setUp()
        source = fixture.claim()
        values = {field: getattr(source, field) for field in source.__dataclass_fields__}
        values.update(
            project_id=base.PROJECT if hasattr(base, "PROJECT") else "project-1",
            source_workflow_run_id="source-run", report_workflow_run_id="report-run",
            design_id="design-1", research_question_ids=("rq-1",), information_need_ids=("need-1",),
            finding_ids=material.finding_ids,
            insight_ids=material.insight_ids, evidence_ids=material.evidence_ids,
            support_evidence_ids=material.evidence_ids, source_ids=material.source_ids,
            finding_content_digests=dict(material.finding_content_digests),
            evidence_content_digests=dict(material.evidence_content_digests),
            insight_content_digests=dict(material.insight_content_digests),
            insight_finding_refs=dict(material.insight_finding_refs),
            source_revision_digests=dict(material.source_revision_digests),
            numeric_observation_proof_digests=dict(material.numeric_observation_proof_digests),
            scope=base.scope, authority_digest="", claim_digest="",
        )
        draft = SimpleNamespace(**values)
        values["authority_digest"] = authority_digest_v2(draft)
        draft.authority_digest = values["authority_digest"]
        values["claim_digest"] = claim_digest_v2(draft)
        self.claim = ReportClaim(**values)
        self.context = ClaimRevisionV2Context(
            design=base.design, findings=(base.finding,), insights=(base.insight,),
            evidence_by_id={base.evidence.id: base.evidence}, source_by_id={base.source.id: base.source},
            temporal_decisions={(base.evidence.id, "need-1"): "applicable_satisfied"},
            allowed_workflow_run_ids=("source-run",), numeric_qualifications={"need-1": base.qualification},
        )
        self.verified_input = VerifiedV2RevisionInput(
            claim=self.claim, verified_proposition=self.claim.proposition,
            finding_ids=self.claim.finding_ids, insight_ids=self.claim.insight_ids,
            evidence_ids=self.claim.evidence_ids, source_ids=self.claim.source_ids,
        )

    def test_rebuilds_new_identity_and_digests_without_side_effects(self):
        result = rebuild_report_claim_v2(self.verified_input, new_report_id="report-2", new_report_revision=2,
                                         report_workflow_run_id="report-run-2", validated_at="2026-01-02T00:00:00Z",
                                         context=self.context)
        self.assertNotEqual(result.claim_id, self.claim.claim_id)
        self.assertEqual(result.proposition, self.claim.proposition)
        self.assertEqual(result.evidence_ids, self.claim.evidence_ids)
        self.assertNotEqual(result.claim_digest, self.claim.claim_digest)
        self.assertEqual(self.claim.report_workflow_run_id, "report-run")

    def test_rejects_changed_source_revision_and_missing_qualification(self):
        changed = replace(self.base.source, content_checksum="x" * 64)
        with self.assertRaises(ClaimRevisionV2Error):
            rebuild_report_claim_v2(self.verified_input, new_report_id="r", new_report_revision=2,
                                    report_workflow_run_id="rr", validated_at="t", context=replace(self.context, source_by_id={changed.id: changed}))
        with self.assertRaises(ClaimRevisionV2Error):
            rebuild_report_claim_v2(self.verified_input, new_report_id="r", new_report_revision=2,
                                    report_workflow_run_id="rr", validated_at="t", context=replace(self.context, numeric_qualifications={}))

    def test_rejects_unsupported_proposition_and_support_mismatch(self):
        with self.assertRaises(ClaimRevisionV2Error):
            rebuild_report_claim_v2(replace(self.verified_input, verified_proposition="tampered"), new_report_id="r", new_report_revision=2,
                                    report_workflow_run_id="rr", validated_at="t", context=self.context)
        with self.assertRaises(ClaimRevisionV2Error):
            rebuild_report_claim_v2(replace(self.verified_input, evidence_ids=("foreign",)), new_report_id="r", new_report_revision=2,
                                    report_workflow_run_id="rr", validated_at="t", context=self.context)


if __name__ == "__main__":
    unittest.main()
