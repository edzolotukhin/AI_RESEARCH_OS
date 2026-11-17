from __future__ import annotations

import io
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from infrastructure.retrieval import bounded_pdf_text_extractor as pdf


def synthetic_pdf(*, pages: int = 1, text: str = "Population 2020: 100 persons") -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output)
    for _ in range(pages):
        if text:
            document.drawString(40, 760, text)
        document.showPage()
    document.save()
    return output.getvalue()


class BoundedPdfTextExtractorTests(unittest.TestCase):
    def test_text_pages_and_empty_image_only_pdf(self) -> None:
        result = pdf._parse_pdf_bytes(synthetic_pdf(pages=2))
        self.assertEqual(result.page_count, 2)
        self.assertIn("Population 2020: 100 persons", result.text)
        with self.assertRaisesRegex(pdf._PdfParseError, "pdf_empty_text"):
            pdf._parse_pdf_bytes(synthetic_pdf(text=""))

    def test_encrypted_malformed_and_truncated_pdf_fail(self) -> None:
        original = synthetic_pdf()
        writer = PdfWriter()
        writer.add_page(PdfReader(io.BytesIO(original)).pages[0])
        writer.encrypt("password")
        encrypted = io.BytesIO()
        writer.write(encrypted)
        with self.assertRaisesRegex(pdf._PdfParseError, "pdf_encrypted"):
            pdf._parse_pdf_bytes(encrypted.getvalue())
        for body in (b"%PDF-1.4\nnot a PDF", original[:-150]):
            with self.subTest(body_size=len(body)):
                with self.assertRaisesRegex(pdf._PdfParseError, "pdf_malformed"):
                    pdf._parse_pdf_bytes(body)

    def test_page_stream_and_text_limits_fail(self) -> None:
        with self.assertRaisesRegex(pdf._PdfParseError, "pdf_page_limit"):
            pdf._parse_pdf_bytes(synthetic_pdf(pages=pdf.MAX_PDF_PAGES + 1))
        with patch.object(pdf, "MAX_PAGE_STREAM_BYTES", 1):
            with self.assertRaisesRegex(pdf._PdfParseError, "pdf_stream_limit"):
                pdf._parse_pdf_bytes(synthetic_pdf())
        with patch.object(pdf, "MAX_PDF_TEXT_CHARS", 5):
            with self.assertRaisesRegex(pdf._PdfParseError, "pdf_text_limit"):
                pdf._parse_pdf_bytes(synthetic_pdf())

    def test_oversized_input_fails_before_process_start(self) -> None:
        with patch.object(pdf.subprocess, "Popen") as spawn:
            result = pdf.extract_pdf_text(b"%PDF-" + b"x" * pdf.MAX_PDF_BYTES)
        self.assertEqual(result.error_code, "pdf_body_limit")
        spawn.assert_not_called()

    def test_timeout_kills_and_reaps_child(self) -> None:
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("pdf-child", 10)
        with patch.object(pdf.sys, "platform", "linux"), patch.object(pdf.subprocess, "Popen", return_value=process):
            result = pdf.extract_pdf_text(b"%PDF-1.4")
        self.assertEqual(result.error_code, "pdf_timeout")
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_ipc_rejects_oversized_and_untrusted_payload(self) -> None:
        with patch.object(pdf.sys, "platform", "linux"):
            with patch.object(pdf.subprocess, "Popen") as spawn:
                process = spawn.return_value
                process.returncode = 0
                process.poll.return_value = 0
                with patch.object(pdf.Path, "is_file", return_value=True), \
                     patch.object(pdf.Path, "stat", return_value=Mock(st_size=pdf.MAX_IPC_BYTES + 1)):
                    result = pdf.extract_pdf_text(b"%PDF-1.4")
        self.assertEqual(result.error_code, "pdf_ipc_invalid")

    @unittest.skipUnless(sys.platform == "linux" and sys.version_info[:2] == (3, 11),
                         "requires the production Linux Python 3.11 runtime")
    def test_actual_linux_child_limits_and_cleanup(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            with patch.object(pdf.tempfile, "TemporaryDirectory", wraps=pdf.tempfile.TemporaryDirectory) as temp_factory:
                result = pdf.extract_pdf_text(synthetic_pdf())
            self.assertIn("Population 2020", result.text)
            self.assertEqual(result.error_code, "")
            self.assertTrue(temp_factory.called)
        self.assertTrue(Path(directory).exists() is False)
        self.assertEqual(pdf.extract_pdf_text(b"%PDF-1.4\nnot a PDF").error_code, "pdf_malformed")
        self.assertEqual(pdf.extract_pdf_text(synthetic_pdf(text="")).error_code, "pdf_empty_text")

    @unittest.skipUnless(sys.platform == "linux" and sys.version_info[:2] == (3, 11),
                         "requires the production Linux Python 3.11 runtime")
    def test_actual_wall_timeout_kills_child(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            sleeper = Path(directory) / "sleeper.py"
            sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            with patch.object(pdf, "__file__", str(sleeper)), \
                 patch.object(pdf, "MAX_PARSER_WALL_SECONDS", 0.1):
                result = pdf.extract_pdf_text(synthetic_pdf())
        self.assertEqual(result.error_code, "pdf_timeout")


if __name__ == "__main__":
    unittest.main()
