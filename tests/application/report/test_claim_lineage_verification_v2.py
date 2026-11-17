from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch
import unittest

from application.report.claim_lineage_verification_v2 import (
    ClaimLineageVerificationV2Error,
    VerifiedClaimLineageV2Snapshot,
    verify_persisted_claim_v2,
    verify_persisted_claim_v2_snapshot,
)
from types import MappingProxyType
from tests.application.report.test_claim_lineage_v2 import ClaimLineageV2Tests
import tests.application.report.test_report_claim_contract as v1_fixtures
import tests.application.report.test_report_claim_v2_contract as v2_fixtures


class ClaimLineageVerificationV2UnitTests(unittest.TestCase):
    def test_verified_snapshot_comes_from_verifier_and_is_detached(self) -> None:
        fixture = ClaimLineageV2Tests(); fixture.setUp()
        revision_fixture = __import__(
            "tests.application.report.test_claim_revision_v2", fromlist=["ClaimRevisionV2Tests"],
        ).ClaimRevisionV2Tests()
        revision_fixture.setUp()
        material = revision_fixture.base.build()
        qualification = replace(
            revision_fixture.base.qualification,
            rejection_reason_counts=MappingProxyType({"none": 0}),
            observations=tuple(
                replace(item, lineage=MappingProxyType(dict(item.lineage)))
                for item in revision_fixture.base.qualification.observations
            ),
        )
        source_run = SimpleNamespace(project_id="project-1", workflow_template_id="template-1")
        template = SimpleNamespace(research_design_snapshot=revision_fixture.base.design, research_brief_snapshot=SimpleNamespace(timeframe=""))
        repos = {
            "finding_repository": SimpleNamespace(get_by_id=lambda key: revision_fixture.base.finding if key == revision_fixture.base.finding.id else None),
            "insight_repository": SimpleNamespace(get_by_id=lambda key: revision_fixture.base.insight if key == revision_fixture.base.insight.id else None),
            "evidence_repository": SimpleNamespace(get_by_id=lambda key: revision_fixture.base.evidence if key == revision_fixture.base.evidence.id else None),
            "source_repository": SimpleNamespace(get_by_id=lambda key: revision_fixture.base.source if key == revision_fixture.base.source.id else None),
            "workflow_run_repository": SimpleNamespace(get_by_id=lambda key: source_run if key == "source-run" else None),
            "workflow_template_repository": SimpleNamespace(get_by_id=lambda key: template if key == "template-1" else None),
        }
        report = SimpleNamespace(project_id="project-1", workflow_run_id="report-run", research_design_id="design-1")
        claim = revision_fixture.claim
        with patch("application.report.claim_lineage_verification_v2.qualify_evidence_with_temporal_decisions") as temporal, \
             patch("application.report.claim_lineage_verification_v2.qualify_numeric_information_need", return_value=qualification):
            temporal.return_value = SimpleNamespace(decisions={(revision_fixture.base.evidence.id, "need-1"): "applicable_satisfied"})
            snapshot = verify_persisted_claim_v2_snapshot(
                claim=claim, report=report, **repos,
            )
        verified, context = snapshot.to_revision_inputs()
        self.assertIs(verified.claim, snapshot.claim)
        self.assertEqual(context.evidence_by_id[revision_fixture.base.evidence.id].id, revision_fixture.base.evidence.id)
        self.assertEqual(snapshot.numeric_qualifications["need-1"].rejection_reason_counts, {"none": 0})
        self.assertIsInstance(snapshot.numeric_qualifications["need-1"].observations[0].lineage, MappingProxyType)
        original = revision_fixture.base.source.content_checksum
        revision_fixture.base.source.metadata["tampered"] = True
        self.assertEqual(snapshot.source_by_id[revision_fixture.base.source.id].content_checksum, original)
        self.assertNotIn("tampered", snapshot.source_by_id[revision_fixture.base.source.id].metadata)
        with self.assertRaises(TypeError):
            snapshot.evidence_by_id["foreign"] = fixture.evidence

    def test_legacy_verify_wrapper_keeps_claim_return_contract(self) -> None:
        revision_fixture = __import__(
            "tests.application.report.test_claim_revision_v2", fromlist=["ClaimRevisionV2Tests"],
        ).ClaimRevisionV2Tests()
        revision_fixture.setUp()
        base = revision_fixture.base
        source_run = SimpleNamespace(project_id="project-1", workflow_template_id="template-1")
        template = SimpleNamespace(research_design_snapshot=base.design, research_brief_snapshot=SimpleNamespace(timeframe=""))
        repos = {
            "finding_repository": SimpleNamespace(get_by_id=lambda key: base.finding),
            "insight_repository": SimpleNamespace(get_by_id=lambda key: base.insight),
            "evidence_repository": SimpleNamespace(get_by_id=lambda key: base.evidence),
            "source_repository": SimpleNamespace(get_by_id=lambda key: base.source),
            "workflow_run_repository": SimpleNamespace(get_by_id=lambda key: source_run),
            "workflow_template_repository": SimpleNamespace(get_by_id=lambda key: template),
        }
        temporal = SimpleNamespace(decisions={(base.evidence.id, "need-1"): "applicable_satisfied"})
        original_claim = revision_fixture.claim
        with patch("application.report.claim_lineage_verification_v2.qualify_evidence_with_temporal_decisions", return_value=temporal), \
             patch("application.report.claim_lineage_verification_v2.qualify_numeric_information_need", return_value=base.qualification):
            result = verify_persisted_claim_v2(
                claim=original_claim,
                report=SimpleNamespace(project_id="project-1", workflow_run_id="report-run", research_design_id="design-1"),
                **repos,
            )
        self.assertIs(result, original_claim)

    def test_actual_lineage_reconstruction_rejects_changed_source_content(self) -> None:
        revision_fixture = __import__(
            "tests.application.report.test_claim_revision_v2", fromlist=["ClaimRevisionV2Tests"],
        ).ClaimRevisionV2Tests()
        revision_fixture.setUp()
        base = revision_fixture.base
        source_run = SimpleNamespace(project_id="project-1", workflow_template_id="template-1")
        template = SimpleNamespace(research_design_snapshot=base.design, research_brief_snapshot=SimpleNamespace(timeframe=""))
        changed_source = __import__("dataclasses").replace(base.source, content_checksum="x" * 64)
        repos = {
            "finding_repository": SimpleNamespace(get_by_id=lambda key: base.finding),
            "insight_repository": SimpleNamespace(get_by_id=lambda key: base.insight),
            "evidence_repository": SimpleNamespace(get_by_id=lambda key: base.evidence),
            "source_repository": SimpleNamespace(get_by_id=lambda key: changed_source),
            "workflow_run_repository": SimpleNamespace(get_by_id=lambda key: source_run),
            "workflow_template_repository": SimpleNamespace(get_by_id=lambda key: template),
        }
        temporal = SimpleNamespace(decisions={(base.evidence.id, "need-1"): "applicable_satisfied"})
        with patch("application.report.claim_lineage_verification_v2.qualify_evidence_with_temporal_decisions", return_value=temporal), \
             patch("application.report.claim_lineage_verification_v2.qualify_numeric_information_need", return_value=base.qualification):
            with self.assertRaises(ClaimLineageVerificationV2Error):
                verify_persisted_claim_v2_snapshot(
                    claim=revision_fixture.claim,
                    report=SimpleNamespace(project_id="project-1", workflow_run_id="report-run", research_design_id="design-1"),
                    **repos,
                )

    def test_v1_is_rejected_without_repository_access(self) -> None:
        fixture = v1_fixtures.ReportClaimContractTests(); fixture.setUp()
        with self.assertRaisesRegex(ClaimLineageVerificationV2Error, "exact ReportClaim v2"):
            verify_persisted_claim_v2(
                claim=fixture.claim(), report=SimpleNamespace(),
                finding_repository=None, insight_repository=None, evidence_repository=None,
                source_repository=None, workflow_run_repository=None,
                workflow_template_repository=None,
            )

    def test_v2_report_context_mismatch_is_rejected_before_authority_load(self) -> None:
        fixture = v2_fixtures.ReportClaimV2ContractTests()
        claim = fixture.claim()
        report = SimpleNamespace(
            project_id="foreign", workflow_run_id=claim.report_workflow_run_id,
            research_design_id=claim.design_id,
        )
        with self.assertRaisesRegex(ClaimLineageVerificationV2Error, "Report context mismatch"):
            verify_persisted_claim_v2(
                claim=claim, report=report,
                finding_repository=None, insight_repository=None, evidence_repository=None,
                source_repository=None, workflow_run_repository=None,
                workflow_template_repository=None,
            )


if __name__ == "__main__":
    unittest.main()
