"""Local production renderer contract: editable OOXML and bounded content."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import re
import unittest
from xml.etree import ElementTree
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

    @staticmethod
    def slide_text(data):
        with ZipFile(BytesIO(data)) as archive:
            names = sorted(
                (name for name in archive.namelist()
                 if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                key=lambda name: int(re.search(r"slide(\d+)", name).group(1)),
            )
            result = []
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                shapes = []
                for shape in root.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}sp"):
                    paragraphs = []
                    for paragraph in shape.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}p"):
                        paragraphs.append("".join(
                            node.text or "" for node in paragraph.findall(
                                ".//{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                            )))
                    shapes.append("\n".join(paragraphs))
                result.append(tuple(shapes))
            return result

    @staticmethod
    def content_tokens(value):
        # Whitespace may be laid out differently by OOXML, but all words,
        # numbers, and punctuation must remain in the exact source order.
        return re.findall(r"\w+|[^\w\s]", value, re.UNICODE)

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

    def test_prf07b_long_desk_text_preserves_words_at_every_continuation(self):
        sentence = ("Це вигаданий приклад для візуальної перевірки документа. "
                    "Умовний матеріал описує лише припущення тестового сценарію; "
                    "він не містить ринкових фактів або порад. ")
        source = "\n\n".join(
            f"Тестовий абзац {index}. " + sentence * 6
            for index in range(1, 11)
        )
        document = replace(self.document, sections=(
            PdfSection("Довгий розділ", (source,), ("CIT-01",)),
        ))
        slides = self.slide_text(self.renderer.render(document))
        bodies = [shape[2] for shape in slides
                  if len(shape) >= 3 and shape[0].startswith("Довгий розділ")]
        self.assertGreater(len(bodies), 5)
        for left, right in zip(bodies, bodies[1:]):
            self.assertFalse(left[-1].isalnum() and right[0].isalnum(),
                             f"Word split at slide boundary: {left[-20:]!r} / {right[:20]!r}")
        self.assertEqual(self.content_tokens(source),
                         self.content_tokens(" ".join(bodies)))
        all_text = " ".join(" ".join(shape) for shape in slides)
        self.assertIn("CIT-01", all_text)
        self.assertIn("Синтетичне обмеження", all_text)

    def test_punctuation_unicode_numbers_and_long_token_preserved(self):
        source = (("Речення 42,5%. Далі слово зі знаком нерозривного пробілу: "
                   "тест\u00a0значення. Mixed English — українська мова!\n\n") * 25
                  + "X" * 90 + " завершення.")
        document = replace(self.document, sections=(
            PdfSection("Unicode", (source,), ()),
        ))
        slides = self.slide_text(self.renderer.render(document))
        bodies = [shape[2] for shape in slides if len(shape) >= 3
                  and shape[0].startswith("Unicode")]
        self.assertGreater(len(bodies), 1)
        self.assertEqual(self.content_tokens(source), self.content_tokens(" ".join(bodies)))
        self.assertTrue(any("X" * 90 in body for body in bodies))

    def test_indivisible_overflow_fails_closed_without_truncation(self):
        document = replace(self.document, sections=(
            PdfSection("Токен", ("X" * 110,), ()),
        ))
        with self.assertRaises(PptxRenderError):
            self.renderer.render(document)

    def test_ordered_source_content_registry_and_limitations_fidelity(self):
        long_heading = "Довгий заголовок українського синтетичного розділу " * 2
        first = "Перший висновок: 42,5%. Джерело лише вигадане. " * 30
        second = "Другий висновок: 17 шт. Інша межа. " * 8
        document = replace(self.document,
            title="Довга назва синтетичного звіту " * 4,
            summary="Резюме з числом 40 і застереженням.",
            sections=(
                PdfSection(long_heading, (first,), ("CIT-01",)),
                PdfSection("Наступний розділ", (second,), ("CIT-02",)),
            ),
            citation_registry=(
                ("CIT-01", "Вигадане джерело — https://example.invalid/one"),
                ("CIT-02", "Друге джерело — https://example.invalid/two"),
            ),
            links=("https://example.invalid/one",),
            limitations=("Обмеження: значення 40 і 17 є синтетичними.",),
        )
        slides = self.slide_text(self.renderer.render(document))
        title_text = " ".join(slides[0])
        for identity in (document.source_id, document.source_version, document.status):
            self.assertIn(identity, title_text)
        body_tokens = self.content_tokens(" ".join(
            shape[2] for shape in slides if len(shape) >= 3
        ))
        cursor = 0
        expected = (
            document.title, document.summary, long_heading, first, "CIT-01",
            second, "CIT-02", "CIT-01: Вигадане джерело — https://example.invalid/one",
            "CIT-02: Друге джерело — https://example.invalid/two",
            "https://example.invalid/one", document.limitations[0],
        )
        for field in expected:
            tokens = self.content_tokens(field)
            match = next((index for index in range(cursor, len(body_tokens) - len(tokens) + 1)
                          if body_tokens[index:index + len(tokens)] == tokens), None)
            self.assertIsNotNone(match, f"Missing or altered source content: {field[:40]!r}")
            cursor = match + len(tokens)


if __name__ == "__main__":
    unittest.main()
