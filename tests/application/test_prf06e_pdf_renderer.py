"""Offline Unicode PDF renderer acceptance on the qualified font stack."""

from __future__ import annotations

from io import BytesIO
import os
import unittest

from application.deliverables.contracts import PdfSection, PdfSourceDocument, PdfTable
from infrastructure.documents.reportlab_pdf_renderer import ReportLabPdfRenderer


class PdfRendererTests(unittest.TestCase):
    def setUp(self):
        self.font = os.environ.get("PDF_FONT_PATH")
        if not self.font:
            self.skipTest("PDF_FONT_PATH not configured for renderer acceptance")
        self.renderer = ReportLabPdfRenderer(self.font)

    def _document(self, body="Довгий український абзац. " * 550):
        return PdfSourceDocument(
            project_id="synthetic-project", method="DESK", run_id="synthetic-run",
            study_id=None, source_id="synthetic-report-v1", source_version="revision-1-review-empty",
            status="Чернетка", title="Синтетичний український звіт",
            summary="Резюме з числом 40, одиницею шт. та цитатою [S1].",
            sections=(PdfSection("Перший розділ", (body,), ("S1",)),),
            limitations=("Обмеження: синтетичні дані не є результатом дослідження.",),
            citation_registry=(("S1", "https://example.invalid/source"),),
            links=("https://example.invalid/source",),
            tables=(PdfTable("Синтетична таблиця", ("Категорія", "Значення"),
                             tuple((f"К-{index}", str(index)) for index in range(70)),
                             base="40 учасників", unit="шт."),),
            revision_number=1,
        )

    def test_rendered_pages_retain_source_identity_text_and_embedded_font(self):
        from pypdf import PdfReader
        data = self.renderer.render(self._document())
        self.assertTrue(data.startswith(b"%PDF-"))
        reader = PdfReader(BytesIO(data))
        self.assertGreater(len(reader.pages), 1)
        text = "\n".join(page.extract_text() for page in reader.pages)
        for value in ("Чернетка", "synthetic-report-v1", "Перший розділ", "Довгий український абзац",
                      "Обмеження", "S1", "https://example.invalid/source", "40", "шт.", "К-69"):
            self.assertIn(value, text)
        self.assertTrue(any(
            "DejaVuSans" in str(font.get_object().get("/BaseFont", "")) and
            font.get_object().get("/FontDescriptor") and
            font.get_object()["/FontDescriptor"].get_object().get("/FontFile2")
            for page in reader.pages for font in page["/Resources"]["/Font"].values()
        ))
        self.assertTrue(any(page.get("/Annots") for page in reader.pages))
        qa_path = os.environ.get("PRF06E_RENDER_QA_PATH")
        if qa_path:
            with open(qa_path, "wb") as output:
                output.write(data)

    def test_oversized_input_rejected_before_render(self):
        with self.assertRaisesRegex(ValueError, "допустимий обсяг"):
            self.renderer.render(self._document("А" * 210_000))
