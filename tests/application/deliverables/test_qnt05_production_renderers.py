"""Offline production-renderer qualification for an approved Quant source."""

from pathlib import Path
import io
import shutil
import unittest
import zipfile

from application.deliverables.quantitative_sources import approved_quantitative_sources
from domain.quantitative.workflow import QuantitativeStudyProjection
from infrastructure.documents.pptx_renderer import PptxRenderer
from infrastructure.documents.reportlab_pdf_renderer import ReportLabPdfRenderer
from tests.application.quantitative import test_qnt04_review as qnt04_fixture


@unittest.skipUnless(
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file()
    and shutil.which("node"),
    "production PDF font and Node runtime required",
)
class QuantitativeProductionRendererTests(unittest.TestCase):
    def test_approved_revision_renders_valid_pdf_and_pptx_offline(self):
        fixture = qnt04_fixture.Qnt04ReviewTests(
            methodName="test_approved_revision_binds_exact_sources_and_replay_is_idempotent")
        fixture.setUp()
        fixture.service.review(project_id=fixture.project_id,
                               run_id=fixture.run_id, state=fixture.state)
        fixture.state_service.persist(
            QuantitativeStudyProjection(
                "study-qnt05-render", fixture.project_id, fixture.run_id,
                "Кількісне дослідження", "offline", "COMPLETED",
                fingerprint="study-qnt05-render-fp"),
            record_id="study-qnt05-render", project_id=fixture.project_id,
            run_id=fixture.run_id)
        document = approved_quantitative_sources(
            state=fixture.state_service, project_id=fixture.project_id,
            run_id=fixture.run_id)[0]
        pdf = ReportLabPdfRenderer().render(document)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf[-1024:])
        pptx = PptxRenderer().render(document)
        self.assertTrue(pptx.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
            names = set(archive.namelist())
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("ppt/presentation.xml", names)
            slides = sorted(name for name in names
                            if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            self.assertGreaterEqual(len(slides), 3)
            text = b"".join(archive.read(name) for name in slides)
            self.assertIn("Synthetic report".encode(), text)
            self.assertIn("42".encode(), text)


if __name__ == "__main__":
    unittest.main()
