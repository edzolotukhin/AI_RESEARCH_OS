from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path, PurePosixPath


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_DOCX_MEMBERS = 512
MAX_DOCX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 16 * 1024 * 1024


def safe_upload_filename(value: str) -> str:
    name = (value or "").strip()
    if not name or len(name) > 255 or _CONTROL.search(name):
        raise ValueError("Upload filename is invalid")
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Upload filename must not contain a path")
    return name


def validate_docx(content: bytes) -> None:
    if not content.startswith(b"PK"):
        raise ValueError("DOCX content does not match its file type")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_DOCX_MEMBERS:
                raise ValueError("DOCX archive member count exceeds supported limits")
            total = 0
            names: set[str] = set()
            for member in members:
                normalized = PurePosixPath(member.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise ValueError("DOCX archive contains an unsafe path")
                if member.flag_bits & 1:
                    raise ValueError("Encrypted DOCX files are unsupported")
                if member.file_size > MAX_DOCX_MEMBER_BYTES:
                    raise ValueError("DOCX archive member exceeds supported limits")
                total += member.file_size
                if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ValueError("DOCX archive expansion exceeds supported limits")
                names.add(normalized.as_posix())
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ValueError("DOCX document structure is invalid")
    except zipfile.BadZipFile as exc:
        raise ValueError("DOCX document structure is invalid") from exc


def validate_quantitative_signature(suffix: str, content: bytes) -> None:
    if suffix == ".xlsx" and not content.startswith(b"PK"):
        raise ValueError("XLSX content does not match its file type")
    if suffix == ".sav" and content[:4] not in {b"$FL2", b"$FL3"}:
        raise ValueError("SAV content does not match its file type")


def validate_audio_signature(suffix: str, content: bytes) -> None:
    valid = {
        "wav": content.startswith(b"RIFF") and content[8:12] == b"WAVE",
        "mp3": content.startswith(b"ID3") or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"},
        "m4a": len(content) >= 12 and content[4:8] == b"ftyp",
        "mp4": len(content) >= 12 and content[4:8] == b"ftyp",
        "webm": content.startswith(b"\x1aE\xdf\xa3"),
    }.get(suffix, False)
    if not valid:
        raise ValueError("Audio content does not match its supported file type")
