"""Synthetic PPTX OOXML structure and content checks; no office rendering claim."""

from __future__ import annotations

from pathlib import Path
from posixpath import dirname, normpath, join
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import unittest

ROOT = Path(__file__).parent / "runs"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def inspect(name: str):
    with ZipFile(ROOT / f"{name}.pptx") as archive:
        assert archive.testzip() is None
        files = set(archive.namelist())
        assert sum(item.file_size for item in archive.infolist()) < 20_000_000
        assert all(item.file_size < 5_000_000 for item in archive.infolist())
        assert not any(path.endswith(("vbaProject.bin", ".exe", ".dll", ".js")) for path in files)
        slides = sorted((path for path in files if path.startswith("ppt/slides/slide")
                         and path.endswith(".xml")),
                        key=lambda path: int(path.removesuffix(".xml").split("slide")[-1]))
        texts = []
        for slide in slides:
            tree = ET.fromstring(archive.read(slide))
            texts.extend(node.text or "" for node in tree.iter(f"{{{A}}}t"))
        for rel_path in (path for path in files if path.endswith(".rels")):
            tree = ET.fromstring(archive.read(rel_path))
            for node in tree.findall(f"{{{REL}}}Relationship"):
                assert node.attrib.get("TargetMode") != "External", (rel_path, node.attrib)
                target = node.attrib.get("Target", "")
                if target.startswith("/") or rel_path == "_rels/.rels":
                    resolved = normpath(target.lstrip("/"))
                else:
                    base = rel_path.replace("/_rels/", "/")[:-5]
                    resolved = normpath(join(dirname(base), target))
                assert resolved in files, (rel_path, target, resolved)
        chart_paths = sorted(path for path in files if path.startswith("ppt/charts/chart")
                             and path.endswith(".xml"))
        chart_text = " ".join(archive.read(path).decode() for path in chart_paths)
        return len(slides), "\n".join(texts), chart_paths, chart_text, files


class OOXMLQualificationTests(unittest.TestCase):
    def test_desk(self):
        count, text, charts, _, files = inspect("desk")
        self.assertEqual(count, 15)
        self.assertFalse(charts)
        for marker in ("synthetic-desk-report-1", "revision-3-review-synthetic",
                       "Статус перевірки не підтверджено", "Резюме", "Контекст",
                       "Матеріали", "Обмеження", "CIT-01", "CIT-02", "example.invalid"):
            self.assertIn(marker, text)
        self.assertEqual(text.count("Довгий"), 55)
        self.assertIn("(продовження)", text)
        self.assertIn("ppt/presentation.xml", files)

    def test_quantitative(self):
        count, text, charts, chart_text, files = inspect("quant")
        self.assertEqual(count, 11)
        self.assertEqual(len(charts), 1)
        for marker in ("synthetic-composition-1", "composition-7", "Прийнято",
                       "Підтверджена таблиця", "Група А", "42", "58", "База:",
                       "Одиниця:", "Обмеження"):
            self.assertIn(marker, text)
        for marker in ("Група А", "Група Б", ">42<", ">58<"):
            self.assertIn(marker, chart_text)
        self.assertTrue(any(path.startswith("ppt/embeddings/") for path in files))
        self.assertIn("(продовження)", text)

    def test_desk_status_variants(self):
        for name, identity, status in (
            ("desk-draft", "synthetic-desk-draft", "Чернетка"),
            ("desk-approved", "synthetic-desk-approved", "Схвалено"),
        ):
            with self.subTest(name=name):
                count, text, charts, _, _ = inspect(name)
                self.assertEqual(count, 15)
                self.assertFalse(charts)
                self.assertIn(identity, text)
                self.assertIn(status, text)


if __name__ == "__main__":
    unittest.main()
