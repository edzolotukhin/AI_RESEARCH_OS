"""QNT-03 offline worker path over disposable PostgreSQL authority."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.methods.quantitative.pin import POST_ANALYSIS_PIN, POST_ANALYSIS_VERSION
from domain.ai.llm_response import LLMResponse
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.review import QuantitativeApprovedRevision, QuantitativeReview
from domain.quantitative.report import QuantitativeReportCompositionResult
from application.quantitative.review import QuantitativeReviewService
from tests.fixtures.quantitative.qnt02_authority_fixture import OWNER, prepare_bound_analysis
from tests.integration.postgresql.helpers import (
    create_test_engine, integration_tests_enabled, postgresql_application_config,
    reset_schema,
)


class _OfflineQuantSemanticClient:
    def __init__(self):
        self.stages = []

    def generate(self, prompt, *, options=None):
        value = prompt.user if hasattr(prompt, "user") else prompt
        if "AUTHORITATIVE_BUNDLE=" in value:
            raise AssertionError("QNT-03 Finding generation must not call a provider")
        if "ACCEPTED_FINDINGS=" in value:
            self.stages.append("insights")
            findings = json.loads(value.split("ACCEPTED_FINDINGS=", 1)[1])
            selected = findings[0]
            response = {"proposals": [{
                "insight_type": "LIMITATION",
                "insight_text": "Interpret this synthetic sample cautiously.",
                "supporting_finding_ids": [selected["finding_id"]],
                "referenced_display_values": [], "direction": None,
                "limitation_note": "Synthetic sample only.",
            }]}
        elif "APPROVED_SUPPORT=" in value:
            self.stages.append("report")
            support = json.loads(value.split("APPROVED_SUPPORT=", 1)[1])
            finding = support["findings"][0]
            insight = support["insights"][0]
            response = {"title": "Synthetic report", "sections": [{
                "section_id": "section-1", "section_type": "KEY_FINDINGS",
                "title": "Bound result", "claim_units": [{
                    "claim_id": "claim-1", "text": finding["text"],
                    "support_mode": "DIRECT_FINDING",
                    "finding_refs": [finding["finding_id"]], "insight_refs": [],
                }],
            }, {
                "section_id": "section-2", "section_type": "LIMITATIONS",
                "title": "Synthetic limitations", "claim_units": [{
                    "claim_id": "claim-2", "text": insight["text"],
                    "support_mode": "EXACT_CONTEXT_INSIGHT",
                    "finding_refs": list(insight["finding_refs"]),
                    "insight_refs": [insight["insight_id"]],
                }],
            }]}
        else:
            raise AssertionError("Unexpected Quant provider boundary")
        return LLMResponse(content=json.dumps(response), output_tokens=7)


class _OfflinePdfRenderer:
    def render(self, document):
        return b"%PDF-1.4\n" + document.source_id.encode() + document.source_version.encode()


class _OfflinePptxRenderer:
    version = "qnt05-pptx-test-v1"
    template_version = "qnt05-template-v1"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    def render(self, document):
        return b"PK\x03\x04" + document.source_id.encode() + document.source_version.encode()


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL test database required")
class Qnt03PostAnalysisPostgresqlTests(unittest.TestCase):
    def test_separate_worker_persists_pinned_findings_and_insights(self):
        engine = create_test_engine()
        self.addCleanup(engine.dispose)
        reset_schema(engine)
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        config = replace(postgresql_application_config(
            deterministic_stage_executors=False, background_execution_mode="external",
        ), projects_root=str(Path(root.name) / "protected"), cmf_quant_enabled=True)
        api_client = _OfflineQuantSemanticClient()
        api = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=Mock(), quantitative_llm_client=api_client,
        ))
        self.addCleanup(api.shutdown)
        fixture = prepare_bound_analysis(api)
        run_id, project_id = fixture["run_id"], fixture["project_id"]
        self.assertEqual(api.workflow_service.get_task_results(run_id)[POST_ANALYSIS_PIN],
                         POST_ANALYSIS_VERSION)
        worker_client = _OfflineQuantSemanticClient()
        worker = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=Mock(), quantitative_llm_client=worker_client,
        ))
        self.addCleanup(worker.shutdown)
        self.assertTrue(worker.worker_execution_service.process_once("qnt03-analysis-worker"))
        self.assertEqual(worker_client.stages, [])
        run = worker.workflow_service.get_workflow_run(run_id)
        paused = next(task for task in run.tasks if task.status.value == "paused")
        boundary = worker.workflow_service.get_task_results(run_id)[paused.id]["shared_state"]["quantitative"]
        worker.quantitative_ui_service.authorize_semantic_execution(
            fixture["study_id"], owner_id=OWNER, actor_id=OWNER,
            expected_authority_fingerprint=boundary["semantic_authority_fingerprint"],
            rationale="Offline QNT-03 acceptance",
        )
        self.assertTrue(worker.worker_execution_service.process_once("qnt03-semantic-worker"))
        results = worker.workflow_service.get_task_results(run_id)
        states = [item.get("shared_state", {}).get("quantitative", {})
                  for item in results.values() if isinstance(item, dict)]
        state = next(item for item in states if item.get("insight_generation_record_id"))
        findings = worker.quantitative_ui_service.state.load(
            state["finding_generation_record_id"], project_id=project_id,
            expected_type=QuantitativeFindingGenerationResult,
        )
        insights = worker.quantitative_ui_service.state.load(
            state["insight_generation_record_id"], project_id=project_id,
            expected_type=QuantitativeInsightGenerationResult,
        )
        self.assertTrue(findings.accepted_findings)
        self.assertEqual(findings.rejected_findings, ())
        self.assertEqual(len(insights.accepted_insights), 1)
        self.assertEqual(insights.rejected_insights, ())
        final_state = next(item for item in states if item.get("terminal_result_record_id"))
        review = worker.quantitative_ui_service.state.load(
            final_state["quant_review_record_id"], project_id=project_id,
            expected_type=QuantitativeReview,
        )
        self.assertEqual(final_state.get("quant_review_verdict"), "approve", review.issues)
        revision = worker.quantitative_ui_service.state.load(
            final_state["quant_approved_revision_record_id"], project_id=project_id,
            expected_type=QuantitativeApprovedRevision,
        )
        self.assertEqual(revision.review_fingerprint, review.fingerprint)
        self.assertEqual(revision.dataset_fingerprint, fixture["dataset_fingerprint"])
        self.assertEqual(worker.review_query_service.final_verdict_for_run(project_id, run_id),
                         "approve")
        deliverables = worker.project_deliverables_service
        deliverables.renderer = _OfflinePdfRenderer()
        deliverables.pptx_renderer = _OfflinePptxRenderer()
        catalog = deliverables.catalog(project_id, owner_id=OWNER)
        self.assertEqual(len(catalog.quantitative), 1)
        source = catalog.quantitative[0].document
        self.assertEqual((source.source_id, source.source_version, source.status),
                         (revision.revision_id, revision.fingerprint, "Схвалено"))
        pdf = deliverables.generate(project_id, "QUANTITATIVE", revision.revision_id,
                                    owner_id=OWNER)
        self.assertEqual(deliverables.download(
            project_id, "QUANTITATIVE", revision.revision_id, pdf.id,
            owner_id=OWNER)[1], deliverables.download(
                project_id, "QUANTITATIVE", revision.revision_id, pdf.id,
                owner_id=OWNER)[1])
        job = deliverables.schedule_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, owner_id=OWNER)
        self.assertEqual(job.source_version, revision.fingerprint)
        self.assertTrue(deliverables.process_next_presentation("qnt05-pg-worker"))
        completed = deliverables.source(
            project_id, "QUANTITATIVE", revision.revision_id,
            owner_id=OWNER).pptx
        first_pptx = deliverables.download_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, completed.id,
            owner_id=OWNER)[1]
        self.assertEqual(first_pptx, deliverables.download_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, completed.id,
            owner_id=OWNER)[1])
        restarted = api.project_deliverables_service
        restarted.pptx_renderer = _OfflinePptxRenderer()
        restored = restarted.catalog(project_id, owner_id=OWNER).quantitative[0]
        self.assertEqual(restored.pdf.id, pdf.id)
        self.assertEqual(restored.pptx.id, completed.id)
        self.assertEqual(restarted.download(
            project_id, "QUANTITATIVE", revision.revision_id, pdf.id,
            owner_id=OWNER)[1], deliverables.download(
                project_id, "QUANTITATIVE", revision.revision_id, pdf.id,
                owner_id=OWNER)[1])
        self.assertEqual(restarted.download_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, completed.id,
            owner_id=OWNER)[1], first_pptx)
        timeline = worker.activity_reader.list_for_project(project_id)
        labels = {item.label for item in timeline.events}
        self.assertIn("Кількісний звіт пройшов перевірку", labels)
        self.assertIn("Затверджено версію кількісного звіту", labels)
        projected = worker.quantitative_ui_service.result_projection(
            fixture["study_id"], owner_id=OWNER)
        self.assertEqual(projected["review"]["verdict"], "approve")
        self.assertEqual(projected["approved_revision"]["id"], revision.revision_id)
        composition = worker.quantitative_ui_service.state.load(
            final_state["report_composition_record_id"], project_id=project_id,
            expected_type=QuantitativeReportCompositionResult,
        )
        broken = replace(composition, accepted_report=replace(
            composition.accepted_report,
            sections=(replace(composition.accepted_report.sections[0],
                              narrative="The synthetic share was 999%."),
                      *composition.accepted_report.sections[1:]),
        ))
        tampered_id = f"{run_id}:tampered-report-for-review-test"
        worker.quantitative_ui_service.state.persist(
            broken, record_id=tampered_id, project_id=project_id, run_id=run_id,
        )
        rejected, rejected_revision = QuantitativeReviewService(
            state_service=worker.quantitative_ui_service.state,
            digest_provider=worker.quantitative_ui_service.state._digest,
            review_repository=worker.review_query_service._review_repository,
        ).review(project_id=project_id, run_id=run_id,
                 state={**final_state, "report_composition_record_id": tampered_id})
        self.assertEqual(rejected.verdict.value, "revise")
        self.assertIsNone(rejected_revision)
        self.assertTrue(rejected.issues)
        self.assertEqual(worker.quantitative_ui_service.state.load(
            revision.revision_id, project_id=project_id,
            expected_type=QuantitativeApprovedRevision), revision)
        self.assertIn("Кількісний звіт потребує виправлення",
                      {item.label for item in worker.activity_reader.list_for_project(project_id).events})
        self.assertEqual(worker_client.stages, ["insights", "report"])
        for finding in findings.accepted_findings:
            self.assertEqual(finding.canonical_authority.dataset_version_id,
                             fixture["dataset_version_id"])
            self.assertEqual(finding.canonical_authority.run_id, run_id)
        self.assertEqual(insights.accepted_insights[0].supporting_finding_refs[0].finding_id,
                         findings.accepted_findings[0].finding_id)
        self.assertNotIn("_research_kernel_v1", results)
        self.assertEqual(api_client.stages, [])
