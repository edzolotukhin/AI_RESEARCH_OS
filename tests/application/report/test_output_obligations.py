"""OUTPUT is transferred as an obligation, never fabricated as a fact."""
from dataclasses import replace
import unittest

from application.report.claim_first_report_service import ClaimFirstReportService
from domain.planning.derivation import InformationNeedKind
from domain.planning.research_design import InformationNeed
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from tests.application.analysis.test_executable_derivations import setup_memory
from tests.application.evidence.test_structured_production import design


class OutputObligationTests(unittest.TestCase):
    def test_report_retains_deferred_requirement_without_claiming_it_satisfied(self):
        base = design()
        model = replace(base, information_needs=(*base.information_needs,
            InformationNeed("table", "rq-pop", "Table of confirmed annual observations",
                kind=InformationNeedKind.OUTPUT, depends_on_information_need_ids=("in-pop",))))
        context, analysis, findings, evidence, sources, _ = setup_memory(model)
        analysis.analyze_for_context(context)
        reports = InMemoryReportRepository()
        claims = InMemoryReportClaimRepository(reports)
        service = ClaimFirstReportService(report_claim_repository=claims, report_engine=DeterministicReportEngine(),
            finding_repository=findings, insight_repository=analysis._insight_repository,
            evidence_repository=evidence, source_repository=sources, report_repository=reports,
            artifact_repository=InMemoryArtifactRepository(), max_findings_per_batch=10, max_chars_per_batch=10000)
        summary = service.write_for_context(context)
        report = reports.get_by_id(summary.report_id)
        obligation = report.metadata["output_obligations"]
        self.assertEqual(obligation, context.read_shared("report_output_obligations"))
        self.assertEqual(obligation["verification_state"], "pending_finalization")
        self.assertEqual(obligation["requirements"][0]["information_need_id"], "table")
        self.assertFalse(obligation["requirements"][0]["satisfied"])
        self.assertTrue(all("table" not in f.information_need_refs for f in findings.list_for_project("project")))
