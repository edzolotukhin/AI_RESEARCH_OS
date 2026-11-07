"""Q2 canonical imported-quantitative qualification over disposable PostgreSQL.

This is intentionally a single end-to-end qualification test.  The semantic
client is deterministic and provider-free; persistence, statistical execution,
review, PDF and PPTX rendering remain production services.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.methods.quantitative.pin import POST_ANALYSIS_PIN, POST_ANALYSIS_VERSION
from domain.ai.llm_response import LLMResponse
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.quality import QualityControlRun
from domain.quantitative.review import QuantitativeApprovedRevision, QuantitativeReview
from domain.quantitative.report import QuantitativeReportCompositionResult
from infrastructure.documents.pptx_renderer import PptxRenderer
from infrastructure.documents.reportlab_pdf_renderer import ReportLabPdfRenderer
from tests.fixtures.quantitative.qnt02_authority_fixture import OWNER, prepare_bound_analysis
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class _DeterministicQuantSemanticClient:
    """Deterministic semantic responses; no external provider is contacted."""

    def generate(self, prompt, *, options=None):
        value = prompt.user if hasattr(prompt, "user") else prompt
        if "AUTHORITATIVE_BUNDLE=" in value:
            raise AssertionError("Finding generation must remain provider-free")
        if "ACCEPTED_FINDINGS=" in value:
            findings = json.loads(value.split("ACCEPTED_FINDINGS=", 1)[1])
            response = {"proposals": [{
                "insight_type": "LIMITATION",
                "insight_text": "Interpret this imported sample cautiously.",
                "supporting_finding_ids": [findings[0]["finding_id"]],
                "referenced_display_values": [],
                "direction": None,
                "limitation_note": "Deterministic qualification fixture.",
            }]}
        elif "APPROVED_SUPPORT=" in value:
            support = json.loads(value.split("APPROVED_SUPPORT=", 1)[1])
            finding = support["findings"][0]
            insight = support["insights"][0]
            response = {"title": "Imported quantitative report", "sections": [{
                "section_id": "section-findings", "section_type": "KEY_FINDINGS",
                "title": "Findings", "claim_units": [{
                    "claim_id": "claim-finding", "text": finding["text"],
                    "support_mode": "DIRECT_FINDING",
                    "finding_refs": [finding["finding_id"]], "insight_refs": [],
                }],
            }, {
                "section_id": "section-limitations", "section_type": "LIMITATIONS",
                "title": "Limitations", "claim_units": [{
                    "claim_id": "claim-limitation", "text": insight["text"],
                    "support_mode": "EXACT_CONTEXT_INSIGHT",
                    "finding_refs": list(insight["finding_refs"]),
                    "insight_refs": [insight["insight_id"]],
                }],
            }]}
        else:
            raise AssertionError("Unexpected quantitative provider boundary")
        return LLMResponse(content=json.dumps(response), output_tokens=7)


def _assert_real_pptx(data: bytes) -> None:
    assert data
    assert data.startswith(b"PK\x03\x04")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names
        ElementTree.fromstring(archive.read("[Content_Types].xml"))
        ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        slides = sorted(
            name for name in names
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
        assert slides
        slide_text = []
        for name in slides:
            root = ElementTree.fromstring(archive.read(name))
            slide_text.extend(
                node.text or ""
                for node in root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")
            )
        assert any(value.strip() for value in slide_text)


@unittest.skipUnless(
    __import__("tests.integration.postgresql.helpers", fromlist=["integration_tests_enabled"])
    .integration_tests_enabled(),
    "Disposable PostgreSQL test database required",
)
class Q2ImportedQuantitativeE2ETests(PostgreSQLIntegrationTestCase):
    def test_imported_quantitative_full_analysis_and_deliverables(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        config = replace(
            postgresql_application_config(
                deterministic_stage_executors=False,
                background_execution_mode="external",
            ),
            projects_root=str(Path(root.name) / "protected"),
            cmf_quant_enabled=True,
        )

        api = create_application_container(
            config=config,
            overrides=ApplicationOverrides(
                llm_client=Mock(),
                quantitative_llm_client=_DeterministicQuantSemanticClient(),
            ),
        )
        self.addCleanup(api.shutdown)
        fixture = prepare_bound_analysis(api)
        run_id, project_id = fixture["run_id"], fixture["project_id"]
        self.assertEqual(api.workflow_service.get_task_results(run_id)[POST_ANALYSIS_PIN], POST_ANALYSIS_VERSION)

        study = api.quantitative_ui_service.get(fixture["study_id"], owner_id=OWNER)
        dataset_before = api.quantitative_ui_service.state.load(
            study.dataset_record_id or "", project_id=project_id, expected_type=DatasetVersion,
        )
        codebook = api.quantitative_ui_service.state.load(
            study.codebook_record_id or "", project_id=project_id, expected_type=CodebookVersion,
        )
        qc = api.quantitative_ui_service.state.load(
            study.qc_record_id or "", project_id=project_id, expected_type=QualityControlRun,
        )
        self.assertEqual(dataset_before.dataset_fingerprint, fixture["dataset_fingerprint"])
        self.assertTrue(codebook.variables)
        self.assertEqual(qc.dataset_fingerprint, dataset_before.dataset_fingerprint)
        self.assertEqual(fixture["dataset_fingerprint"], dataset_before.dataset_fingerprint)

        worker = create_application_container(
            config=config,
            overrides=ApplicationOverrides(
                llm_client=Mock(),
                quantitative_llm_client=_DeterministicQuantSemanticClient(),
            ),
        )
        self.addCleanup(worker.shutdown)
        self.assertTrue(worker.worker_execution_service.process_once("q2-analysis-worker"))
        run = worker.workflow_service.get_workflow_run(run_id)
        paused = next(task for task in run.tasks if task.status.value == "paused")
        boundary = worker.workflow_service.get_task_results(run_id)[paused.id]["shared_state"]["quantitative"]
        worker.quantitative_ui_service.authorize_semantic_execution(
            fixture["study_id"], owner_id=OWNER, actor_id=OWNER,
            expected_authority_fingerprint=boundary["semantic_authority_fingerprint"],
            rationale="Q2 imported quantitative qualification",
        )
        self.assertTrue(worker.worker_execution_service.process_once("q2-semantic-worker"))

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
        self.assertTrue(insights.accepted_insights)
        self.assertEqual(insights.rejected_insights, ())

        final_state = next(item for item in states if item.get("terminal_result_record_id"))
        review = worker.quantitative_ui_service.state.load(
            final_state["quant_review_record_id"], project_id=project_id, expected_type=QuantitativeReview,
        )
        revision = worker.quantitative_ui_service.state.load(
            final_state["quant_approved_revision_record_id"], project_id=project_id,
            expected_type=QuantitativeApprovedRevision,
        )
        self.assertEqual(review.verdict.value, "approve")
        self.assertEqual(revision.review_fingerprint, review.fingerprint)
        self.assertEqual(revision.dataset_fingerprint, fixture["dataset_fingerprint"])
        self.assertEqual(worker.review_query_service.final_verdict_for_run(project_id, run_id), "approve")

        deliverables = worker.project_deliverables_service
        self.assertIsInstance(deliverables.renderer, ReportLabPdfRenderer)
        self.assertIsInstance(deliverables.pptx_renderer, PptxRenderer)
        catalog = deliverables.catalog(project_id, owner_id=OWNER)
        source = catalog.quantitative[0].document
        self.assertEqual(source.source_id, revision.revision_id)
        pdf = deliverables.generate(project_id, "QUANTITATIVE", revision.revision_id, owner_id=OWNER)
        pdf_record, pdf_bytes = deliverables.download(
            project_id, "QUANTITATIVE", revision.revision_id, pdf.id, owner_id=OWNER,
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(hashlib.sha256(pdf_bytes).hexdigest(), pdf_record.checksum)
        job = deliverables.schedule_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, owner_id=OWNER,
        )
        self.assertEqual(job.source_version, revision.fingerprint)
        self.assertTrue(deliverables.process_next_presentation("q2-presentation-worker"))
        completed = deliverables.source(project_id, "QUANTITATIVE", revision.revision_id, owner_id=OWNER).pptx
        pptx_record, pptx_bytes = deliverables.download_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, completed.id, owner_id=OWNER,
        )
        _assert_real_pptx(pptx_bytes)
        self.assertEqual(hashlib.sha256(pptx_bytes).hexdigest(), pptx_record.checksum)

        fresh = create_application_container(
            config=config,
            overrides=ApplicationOverrides(
                llm_client=Mock(),
                quantitative_llm_client=_DeterministicQuantSemanticClient(),
            ),
        )
        self.addCleanup(fresh.shutdown)
        fresh_dataset = fresh.quantitative_ui_service.state.load(
            study.dataset_record_id or "", project_id=project_id, expected_type=DatasetVersion,
        )
        self.assertEqual(fresh_dataset.data_fingerprint, dataset_before.data_fingerprint)
        self.assertEqual(fresh_dataset.dataset_fingerprint, dataset_before.dataset_fingerprint)
        fresh_findings = fresh.quantitative_ui_service.state.load(
            state["finding_generation_record_id"], project_id=project_id,
            expected_type=QuantitativeFindingGenerationResult,
        )
        fresh_insights = fresh.quantitative_ui_service.state.load(
            state["insight_generation_record_id"], project_id=project_id,
            expected_type=QuantitativeInsightGenerationResult,
        )
        self.assertEqual(fresh_findings.accepted_findings, findings.accepted_findings)
        self.assertEqual(fresh_insights.accepted_insights, insights.accepted_insights)
        fresh_catalog = fresh.project_deliverables_service.catalog(project_id, owner_id=OWNER)
        self.assertEqual(fresh_catalog.quantitative[0].pdf.id, pdf.id)
        self.assertEqual(fresh_catalog.quantitative[0].pptx.id, completed.id)
        self.assertEqual(fresh.project_deliverables_service.download(
            project_id, "QUANTITATIVE", revision.revision_id, pdf.id, owner_id=OWNER,
        )[1], pdf_bytes)
        self.assertEqual(fresh.project_deliverables_service.download_presentation(
            project_id, "QUANTITATIVE", revision.revision_id, completed.id, owner_id=OWNER,
        )[1], pptx_bytes)
        self.assertEqual(fresh.review_query_service.final_verdict_for_run(project_id, run_id), "approve")
        composition = fresh.quantitative_ui_service.state.load(
            final_state["report_composition_record_id"], project_id=project_id,
            expected_type=QuantitativeReportCompositionResult,
        )
        self.assertIsNotNone(composition.accepted_report)
