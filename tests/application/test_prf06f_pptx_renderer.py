"""Local production renderer contract: editable OOXML and bounded content."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import unittest
from zipfile import ZipFile

from application.deliverables.contracts import PdfSection, PdfSourceDocument, PdfTable, PresentationChart
from infrastructure.documents.pptx_renderer import PptxRenderError, PptxRenderer


class PptxRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = PptxRenderer()
        self.document = PdfSourceDocument(
            project_id="synthetic-project", method="DESK", run_id="synthetic-run",
            study_id=None, source_id="synthetic-report", source_version="revision-2",
            status="Схвалено", title="Синтетичний звіт", summary="Збережене резюме",
            sections=(PdfSection("Розділ", ("Український текст" * 100,), ("CIT-01",)),),
            limitations=("Синтетичне обмеження",),
            citation_registry=(("CIT-01", "Локально збережене джерело"),),
        )

    @staticmethod
    def parts(data):
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            slides = sorted(name for name in names if name.startswith("ppt/slides/slide")
                            and name.endswith(".xml"))
            text = " ".join(archive.read(name).decode("utf-8") for name in slides)
            return names, slides, text

    def test_desk_preserves_saved_content_and_continuation(self):
        names, slides, text = self.parts(self.renderer.render(self.document))
        self.assertGreater(len(slides), 3)
        self.assertIn("Український текст", text)
        self.assertIn("Схвалено", text)
        self.assertIn("synthetic-report", text)
        self.assertIn("CIT-01", text)
        self.assertIn("Синтетичне обмеження", text)
        self.assertIn("продовження", text)
        self.assertFalse(any("vbaProject.bin" in name for name in names))

    def test_quantitative_native_table_and_supported_chart(self):
        document = replace(self.document, method="QUANTITATIVE", status="Прийнято",
            source_version="composition-1", tables=(PdfTable("Підтверджена таблиця",
            ("Група", "Значення"), (("А", "42"), ("Б", "58")), "учасники", "%"),),
            charts=(PresentationChart("Підтверджений графік", ("А", "Б"), (42, 58),
                                      "учасники", "%"),))
        names, _, text = self.parts(self.renderer.render(document))
        self.assertTrue(any(name.startswith("ppt/charts/chart") and name.endswith(".xml") for name in names))
        self.assertTrue(any(name.startswith("ppt/embeddings/") for name in names))
        self.assertIn("42", text)
        self.assertIn("58", text)
        self.assertIn("учасники", text)

    def test_chart_without_base_is_omitted_without_inventing_values(self):
        document = replace(self.document, charts=(PresentationChart(
            "Непідтверджений графік", ("А",), (42,), None, "%"),))
        names, _, _ = self.parts(self.renderer.render(document))
        self.assertFalse(any(name.startswith("ppt/charts/chart") for name in names))

    def test_header_only_table_and_long_titles_remain_visible(self):
        table_title = "Назва таблиці " * 8
        chart_title = "Назва графіка " * 8
        document = replace(self.document, tables=(PdfTable(
            table_title, ("Група", "Значення"), (), "усі", "%"),),
            charts=(PresentationChart(chart_title, ("А",), (42,), "усі", "%"),))
        names, _, text = self.parts(self.renderer.render(document))
        self.assertTrue(any(name.startswith("ppt/charts/chart") for name in names))
        self.assertIn(table_title, text)
        self.assertIn(chart_title, text)
        self.assertIn("Група", text)
        self.assertIn("Значення", text)

    def test_oversized_source_fails_without_binary(self):
        document = replace(self.document, summary="X" * 210_000)
        with self.assertRaises(PptxRenderError):
            self.renderer.render(document)


if __name__ == "__main__":
    unittest.main()
