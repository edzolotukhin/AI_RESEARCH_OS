"""Bounded offline ReportLab renderer for canonical saved report content."""

from __future__ import annotations

from html import escape
from xml.sax.saxutils import quoteattr
from io import BytesIO
from pathlib import Path
import os
from urllib.parse import urlsplit

from application.deliverables.contracts import PdfSourceDocument


class ReportLabPdfRenderer:
    MAX_SOURCE_CHARS = 200_000

    def __init__(self, font_path: str | None = None) -> None:
        self.font_path = Path(font_path or os.environ.get("PDF_FONT_PATH") or
                              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

    def render(self, document: PdfSourceDocument) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle
        values = [document.title, document.status, document.summary or "",
                  *document.limitations, *document.unavailable]
        for section in document.sections:
            values.extend((section.title, *section.paragraphs, *section.citations))
        values.extend(f"{key} {value}" for key, value in document.citation_registry)
        values.extend(document.links)
        for table in document.tables:
            if len(table.rows) > 1_000 or not table.headers or any(len(row) != len(table.headers) for row in table.rows):
                raise ValueError("Таблиця перевищує допустимий обсяг PDF")
            values.extend((table.title, table.base or "", table.unit or "", *table.headers))
            values.extend(cell for row in table.rows for cell in row)
        if sum(len(value) for value in values) > self.MAX_SOURCE_CHARS:
            raise ValueError("Звіт перевищує допустимий обсяг PDF")
        if not self.font_path.is_file():
            raise RuntimeError("PDF font unavailable")
        pdfmetrics.registerFont(TTFont("PRF06E-DejaVu", str(self.font_path)))
        body = ParagraphStyle("body", fontName="PRF06E-DejaVu", fontSize=10, leading=15,
                              textColor=colors.HexColor("#1b2b3d"), spaceAfter=8,
                              splitLongWords=True)
        title = ParagraphStyle("title", parent=body, fontSize=17, leading=22, spaceAfter=12)
        heading = ParagraphStyle("heading", parent=body, fontSize=13, leading=18, spaceBefore=12)
        small = ParagraphStyle("small", parent=body, fontSize=8, leading=12)
        output = BytesIO()
        story = []

        def add(value: str, style=body):
            # Paragraph handles wrapping/page breaks; source text is never abbreviated.
            for line in (value.splitlines() or [""]):
                story.append(Paragraph(escape(line) or "&#160;", style))

        add(document.title, title)
        add(f"{document.method} · {document.status}", heading)
        add(f"Проєкт: {document.project_id} · Дослідження: {document.run_id}", small)
        add(f"Звіт: {document.source_id} · Джерело: {document.source_version}", small)
        if document.study_id:
            add(f"Кількісне дослідження: {document.study_id}", small)
        if document.revision_number is not None:
            add(f"Редакція: {document.revision_number}", small)
        if document.created_at:
            add(f"Створено: {document.created_at}", small)
        if document.summary:
            add("Резюме", heading)
            add(document.summary)
        for section in document.sections:
            add(section.title, heading)
            for paragraph in section.paragraphs:
                add(paragraph)
            if section.citations:
                add("Цитати: " + ", ".join(section.citations), small)
        for table in document.tables:
            add(table.title, heading)
            if table.base or table.unit:
                add(" · ".join(value for value in (table.base, table.unit) if value), small)
            matrix = (table.headers, *table.rows)
            wrapped = [[Paragraph(escape(str(cell)), small) for cell in row] for row in matrix]
            widths = [485.28 / len(table.headers)] * len(table.headers)
            grid = LongTable(wrapped, colWidths=widths, repeatRows=1, splitByRow=1)
            grid.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef3")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ccd5dd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(grid)
        if document.citation_registry:
            add("Реєстр джерел", heading)
            for key, value in document.citation_registry:
                add(f"{key}: {value}", small)
            for url in document.links:
                parsed = urlsplit(url)
                if parsed.scheme in {"http", "https"} and parsed.netloc and len(url) <= 2048:
                    story.append(Paragraph(
                        f'<link href={quoteattr(url)} color="#0b5a8a">{escape(url)}</link>', small))
        if document.limitations and document.method != "QUANTITATIVE":
            add("Обмеження", heading)
            for limitation in document.limitations:
                add(limitation)
        for unavailable in document.unavailable:
            add(unavailable, small)
        SimpleDocTemplate(output, pagesize=(595.28, 841.89), leftMargin=55,
                          rightMargin=55, topMargin=52, bottomMargin=52).build(story)
        return output.getvalue()
