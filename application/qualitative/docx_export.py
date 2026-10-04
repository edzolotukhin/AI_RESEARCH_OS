from __future__ import annotations
import io, zipfile
from xml.sax.saxutils import escape
from domain.qualitative.authority import TranscriptVersion


def _time(ms):
    seconds = ms // 1000
    return f"{seconds//3600:02d}:{(seconds//60)%60:02d}:{seconds%60:02d}"


def render_transcript_docx(transcript: TranscriptVersion, *, session_id: str, participant: str) -> bytes:
    paragraphs = [f"Interview {session_id}", f"Participant {participant}",
                  f"Source: {transcript.source_mode.value}", f"Transcript version: {transcript.version}"]
    if transcript.language: paragraphs.append(f"Language: {transcript.language}")
    for segment in transcript.segments:
        label = segment.speaker_label or segment.speaker_role.value.title()
        if segment.start_ms is not None: label = f"{_time(segment.start_ms)} — {label}"
        paragraphs.extend((label, segment.text))
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(value)}</w:t></w:r></w:p>" for value in paragraphs)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}<w:sectPr/></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in (("[Content_Types].xml", content_types), ("_rels/.rels", rels),
                            ("word/document.xml", document)):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value.encode("utf-8"))
    return output.getvalue()
