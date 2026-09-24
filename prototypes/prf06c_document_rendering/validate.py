"""Prototype-only content, package, checksum, and bounded-failure checks."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from fixtures import DESK, QUANT
from prototype import OUT, normalize


def slide_text(path: Path) -> tuple[str, int, int]:
    with zipfile.ZipFile(path) as package:
        assert package.testzip() is None
        slides = sorted((p for p in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", p)),
                        key=lambda p: int(re.search(r"\d+", p).group()))
        text = "\n".join(" ".join(element.text or "" for element in ET.fromstring(package.read(slide)).iter()
                                if element.tag.endswith("}t")) for slide in slides)
        return text, len(slides), sum(1 for p in package.namelist() if re.fullmatch(r"ppt/(?:slides/)?charts/chart\d+\.xml", p))


class PrototypeValidation(unittest.TestCase):
    def test_pdf_identity_and_content(self):
        for name, source in (("desk", DESK), ("quantitative", QUANT)):
            with self.subTest(name=name):
                reader = PdfReader(str(OUT / f"{name}.pdf"))
                body = "\n".join(page.extract_text() for page in reader.pages)
                for required in (source["title"], source["report_id"], source["source_status"],
                                 *[section["title"] for section in source["sections"]],
                                 *source["limitations"], *[item["id"] for item in source["sources"]]):
                    self.assertIn(required, body)
                self.assertGreater(len(reader.pages), 1)
                self.assertTrue(any(page.get("/Annots") for page in reader.pages))
                fonts = [font.get_object() for page in reader.pages
                         for font in page["/Resources"]["/Font"].values()]
                self.assertTrue(any("DejaVuSans" in str(font.get("/BaseFont", ""))
                                    and font.get("/FontDescriptor")
                                    and font["/FontDescriptor"].get_object().get("/FontFile2")
                                    for font in fonts), "embedded DejaVuSans font missing")
                self.assertEqual(body.count("Синтетичний текст для перевірки"), 38)
                if name == "quantitative":
                    self.assertIn("К-17", body)
                    self.assertIn("40", body)

    def test_pptx_structure_and_source_identity(self):
        expected = {"desk": (DESK, 17, 0), "quantitative": (QUANT, 21, 1)}
        for name, (source, min_slides, chart_count) in expected.items():
            with self.subTest(name=name):
                body, slide_count, charts = slide_text(OUT / f"{name}.pptx")
                self.assertGreaterEqual(slide_count, min_slides)
                self.assertEqual(charts, chart_count)
                for required in (source["title"], source["report_id"], source["source_status"],
                                 *[section["title"] for section in source["sections"]],
                                 *source["limitations"], *[item["id"] for item in source["sources"]]):
                    self.assertIn(required, body)
                if name == "quantitative":
                    self.assertIn("12", body)
                    self.assertIn("18", body)
                    self.assertIn("40", body)
                    self.assertNotIn("Неповні дані", body)
                    self.assertIn("К-17", body)
                self.assertEqual(body.count("Синтетичний текст для перевірки"), 38)

    def test_preview_bound_to_saved_pptx(self):
        manifest = json.loads((OUT / "saved_preview_manifest.json").read_text(encoding="utf-8"))
        for name in ("desk", "quantitative"):
            source = OUT / f"{name}.pptx"
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), manifest[name]["source_sha256"])
            self.assertIn("imported-pptx", manifest[name]["renderer"])
            for asset in manifest[name]["assets"]:
                self.assertTrue((OUT / asset["filename"]).is_file())

    def test_oversized_fails_without_truncation(self):
        too_long = dict(DESK)
        too_long["summary"] = "Д" * 110_000
        with self.assertRaisesRegex(ValueError, "character budget"):
            normalize(too_long)
        too_many_rows = dict(QUANT)
        too_many_rows["tables"] = [{**QUANT["tables"][0], "rows": [["А", "1", "40", "од."]] * 1001}]
        with self.assertRaisesRegex(ValueError, "row budget"):
            normalize(too_many_rows)


if __name__ == "__main__":
    if sys.argv[1:] == ["--pdf-only"]:
        suite = unittest.TestSuite([
            PrototypeValidation("test_pdf_identity_and_content"),
            PrototypeValidation("test_oversized_fails_without_truncation"),
        ])
        raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    unittest.main(verbosity=2)
