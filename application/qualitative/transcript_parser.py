from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from domain.qualitative.authority import SpeakerRole, TranscriptSegment

_LINE = re.compile(r"^(?:(?:\[(\d{1,2}:\d{2}(?::\d{2})?)\]|(\d{1,2}:\d{2}(?::\d{2})?))\s*[-–—]?\s*)?(?:([^:]{1,40}):\s*)?(.*)$")


def _milliseconds(value: str | None) -> int | None:
    if value is None:
        return None
    parts = [int(x) for x in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    else:
        hours, minutes, seconds = parts
    if minutes > 59 or seconds > 59:
        raise ValueError("Invalid transcript timestamp")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def _role(label: str | None) -> SpeakerRole:
    normalized = (label or "").strip().casefold()
    if normalized in {"i", "interviewer", "moderator", "інтерв'юер", "модератор"}:
        return SpeakerRole.INTERVIEWER
    if normalized == "participant" or re.fullmatch(r"p\d+", normalized):
        return SpeakerRole.PARTICIPANT
    return SpeakerRole.UNKNOWN


def parse_prepared_text(text: str) -> tuple[TranscriptSegment, ...]:
    segments = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if not match:
            continue
        timestamp = _milliseconds(match.group(1) or match.group(2))
        label, body = match.group(3), match.group(4).strip()
        if not body:
            continue
        segments.append(TranscriptSegment(
            segment_id=f"segment-{len(segments) + 1:04d}", order=len(segments), text=body,
            speaker_label=label.strip() if label else None, speaker_role=_role(label),
            start_ms=timestamp, end_ms=timestamp,
        ))
    if not segments:
        raise ValueError("Prepared transcript contains no usable text")
    return tuple(segments)


def parse_docx(content: bytes) -> tuple[TranscriptSegment, ...]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("Invalid DOCX transcript") from exc
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(namespace + "p"):
        value = "".join(node.text or "" for node in paragraph.iter(namespace + "t")).strip()
        if value:
            paragraphs.append(value)
    return parse_prepared_text("\n".join(paragraphs))
