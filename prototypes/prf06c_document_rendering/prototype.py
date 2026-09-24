"""Bounded direct-PDF experiment using synthetic fixture data only."""

from __future__ import annotations

import json
import os
import re
import time
import tracemalloc
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from fixtures import DESK, QUANT

ROOT = Path(__file__).resolve().parent
RUN_NAME = os.environ.get("PRF06C_RUN_NAME", "")
if RUN_NAME and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", RUN_NAME):
    raise ValueError("invalid prototype run name")
OUT = ROOT / "runs" / RUN_NAME / "output" if RUN_NAME else ROOT / "output"
FONT_PATH = os.environ.get("PRF06C_FONT_PATH")
if os.name == "nt" and not FONT_PATH:
    raise RuntimeError("set PRF06C_FONT_PATH to an installed DejaVuSans.ttf")
FONT = Path(FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
MAX_CHARS = 100_000
MAX_TABLE_ROWS = 1_000
GENERATED = "2026-09-24T00:00:00Z"  # fixed prototype clock for reproducibility


def normalize(source: dict) -> dict:
    """Preserve fixture text/values; never derive conclusions or statistics."""
    doc = {key: source[key] for key in (
        "method", "project", "report_id", "revision", "composition_id", "source_status",
        "title", "summary", "sections", "tables", "charts", "limitations", "sources", "missing",
    )}
    doc["generated_at"] = GENERATED
    if sum(len(str(value)) for value in doc.values()) > MAX_CHARS:
        raise ValueError("synthetic document exceeds character budget")
    if any(len(table["rows"]) > MAX_TABLE_ROWS for table in doc["tables"]):
        raise ValueError("synthetic table exceeds row budget")
    for chart in doc["charts"]:
        chart["render_chart"] = bool(
            chart["eligible"] and chart["unit"] and chart["base"] and chart["source_ref"]
            and len(chart["categories"]) == len(chart["values"])
        )
    return doc


def build_pdf(doc: dict, path: Path) -> dict:
    pdfmetrics.registerFont(TTFont("PRF-DejaVu", str(FONT)))
    style = ParagraphStyle("body", fontName="PRF-DejaVu", fontSize=10, leading=15,
                           textColor=colors.HexColor("#1b2b3d"), alignment=TA_LEFT,
                           splitLongWords=True, spaceAfter=8)
    title = ParagraphStyle("title", parent=style, fontSize=18, leading=23, spaceAfter=12)
    heading = ParagraphStyle("heading", parent=style, fontSize=13, leading=18, spaceBefore=14)
    tiny = ParagraphStyle("tiny", parent=style, fontSize=8, leading=11)
    story = []
    add = lambda value, which=style: story.append(Paragraph(escape(str(value)), which))
    add(doc["title"], title)
    add(f"{doc['method']} · {doc['project']} · {doc['source_status']}")
    add(f"Звіт {doc['report_id']} · версія {doc['revision'] if doc['revision'] is not None else doc['composition_id']}")
    add(f"Створено: {doc['generated_at']}", tiny)
    add("Резюме", heading)
    add(doc["summary"])
    for section in doc["sections"]:
        add(section["title"], heading)
        add(section["text"])
        if section["citations"]:
            add("Джерела: " + ", ".join(section["citations"]), tiny)
    for table in doc["tables"]:
        add(table["title"], heading)
        add(table["qualification"] + " · " + table["source_ref"], tiny)
        matrix = [table["headers"], *table["rows"]]
        wrapped = [[Paragraph(escape(str(cell)), tiny) for cell in row] for row in matrix]
        grid = LongTable(wrapped, colWidths=[110, 105, 105, 105], repeatRows=1, splitByRow=1)
        grid.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef3")),
            ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#ccd5dd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([grid, Spacer(1, 10)])
    add("Обмеження", heading)
    for item in doc["limitations"]:
        add(item)
    add("Джерела", heading)
    for source in doc["sources"]:
        label = escape(source["id"] + " — " + source["title"] + ": ")
        url = escape(source["url"], quote=True)
        # No resource fetch. This creates an external hyperlink annotation only.
        story.append(Paragraph(label + f'<link href="{url}">{url}</link>', tiny))
    build = SimpleDocTemplate(str(path), pagesize=(595, 842), leftMargin=55,
                              rightMargin=55, topMargin=52, bottomMargin=52,
                              title=doc["title"], author="PRF-06C synthetic prototype")
    def footer(canvas, _):
        canvas.saveState()
        canvas.setFont("PRF-DejaVu", 8)
        canvas.drawString(55, 27, f"{doc['source_status']} · {doc['report_id']}")
        canvas.drawRightString(540, 27, f"{canvas.getPageNumber()}")
        canvas.restoreState()
    tracemalloc.start()
    started = time.perf_counter()
    build.build(story, onFirstPage=footer, onLaterPages=footer)
    elapsed = round(time.perf_counter() - started, 3)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    reader = PdfReader(str(path))
    return {"seconds": elapsed, "bytes": path.stat().st_size,
            "pages": len(reader.pages), "python_peak_bytes": peak}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = {}
    for name, source in (("desk", DESK), ("quantitative", QUANT)):
        doc = normalize(source)
        (OUT / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        metrics[name] = build_pdf(doc, OUT / f"{name}.pdf")
    (OUT / "pdf_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
