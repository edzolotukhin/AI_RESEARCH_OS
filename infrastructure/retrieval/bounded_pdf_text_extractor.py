"""Bounded text extraction from untrusted PDF bytes in a separate Linux process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


PDF_EXTRACTION_REVISION = "pdf-text-pypdf-6.12.2-v1"
MAX_PDF_BYTES = 512_000
MAX_PDF_PAGES = 20
MAX_PAGE_STREAM_BYTES = 2 * 1024 * 1024
MAX_PDF_TEXT_CHARS = 100_000
MAX_IPC_BYTES = 512 * 1024
MAX_PARSER_MEMORY_BYTES = 512 * 1024 * 1024
MAX_PARSER_CPU_SECONDS = 5
MAX_PARSER_WALL_SECONDS = 10

PDF_ERROR_CODES = frozenset({
    "pdf_body_limit", "pdf_mime_mismatch", "pdf_encrypted", "pdf_malformed",
    "pdf_page_limit", "pdf_stream_limit", "pdf_text_limit", "pdf_empty_text",
    "pdf_timeout", "pdf_child_failed", "pdf_runtime_unavailable", "pdf_ipc_invalid",
})


@dataclass(frozen=True)
class PdfTextResult:
    text: str = ""
    page_count: int = 0
    error_code: str = ""


class _PdfParseError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _parse_pdf_bytes(body: bytes) -> PdfTextResult:
    """Parse only inside the bounded child; direct calls are for synthetic tests."""
    from io import BytesIO
    from pypdf import PdfReader

    if len(body) > MAX_PDF_BYTES or not body.startswith(b"%PDF-"):
        raise _PdfParseError("pdf_body_limit" if len(body) > MAX_PDF_BYTES else "pdf_mime_mismatch")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted:
            raise _PdfParseError("pdf_encrypted")
        page_count = len(reader.pages)
        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise _PdfParseError("pdf_page_limit")
        text_parts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PAGE_STREAM_BYTES:
                raise _PdfParseError("pdf_stream_limit")
            text = page.extract_text() or ""
            total_chars += len(text)
            if total_chars > MAX_PDF_TEXT_CHARS:
                raise _PdfParseError("pdf_text_limit")
            text_parts.append(text)
        extracted = "\n".join(text_parts).strip()
        if len(extracted) > MAX_PDF_TEXT_CHARS:
            raise _PdfParseError("pdf_text_limit")
        if not extracted:
            raise _PdfParseError("pdf_empty_text")
        return PdfTextResult(text=extracted, page_count=page_count)
    except _PdfParseError:
        raise
    except Exception as exc:
        raise _PdfParseError("pdf_malformed") from exc


def _child_main(output_path: str) -> int:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_PARSER_MEMORY_BYTES, MAX_PARSER_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_PARSER_CPU_SECONDS, MAX_PARSER_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_IPC_BYTES, MAX_IPC_BYTES))
        active_limits = {
            "memory_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
            "cpu_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0],
            "file_bytes": resource.getrlimit(resource.RLIMIT_FSIZE)[0],
        }
        body = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
        try:
            result = _parse_pdf_bytes(body)
            payload = {"text": result.text, "page_count": result.page_count, "limits": active_limits}
        except _PdfParseError as exc:
            payload = {"error_code": exc.code, "limits": active_limits}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8", errors="replace")
        if len(encoded) > MAX_IPC_BYTES:
            payload = {"error_code": "pdf_ipc_invalid"}
            encoded = json.dumps(payload).encode("ascii")
        descriptor = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        return 0
    except BaseException:
        # No parser exceptions or PDF content may reach stderr or parent diagnostics.
        return 1


def extract_pdf_text(body: bytes) -> PdfTextResult:
    if len(body) > MAX_PDF_BYTES:
        return PdfTextResult(error_code="pdf_body_limit")
    if not body.startswith(b"%PDF-"):
        return PdfTextResult(error_code="pdf_mime_mismatch")
    if sys.platform != "linux":
        return PdfTextResult(error_code="pdf_runtime_unavailable")

    try:
        with tempfile.TemporaryDirectory(prefix="airos-pdf-") as directory:
            output_path = Path(directory) / "result.json"
            try:
                process = subprocess.Popen(
                    [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", str(output_path)],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=directory, env={"PYTHONIOENCODING": "utf-8"},
                )
            except OSError:
                return PdfTextResult(error_code="pdf_runtime_unavailable")
            try:
                process.communicate(input=body, timeout=MAX_PARSER_WALL_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return PdfTextResult(error_code="pdf_timeout")
            except OSError:
                return PdfTextResult(error_code="pdf_child_failed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode != 0 or not output_path.is_file():
                return PdfTextResult(error_code="pdf_child_failed")
            try:
                if output_path.stat().st_size > MAX_IPC_BYTES:
                    return PdfTextResult(error_code="pdf_ipc_invalid")
                with output_path.open("rb") as output:
                    payload = json.loads(output.read(MAX_IPC_BYTES + 1))
                if not isinstance(payload, dict):
                    return PdfTextResult(error_code="pdf_ipc_invalid")
                if payload.get("limits") != {
                    "memory_bytes": MAX_PARSER_MEMORY_BYTES,
                    "cpu_seconds": MAX_PARSER_CPU_SECONDS,
                    "file_bytes": MAX_IPC_BYTES,
                }:
                    return PdfTextResult(error_code="pdf_ipc_invalid")
                code = payload.get("error_code")
                if code is not None:
                    return PdfTextResult(error_code=code if isinstance(code, str) and code in PDF_ERROR_CODES else "pdf_ipc_invalid")
                text, page_count = payload.get("text"), payload.get("page_count")
                if (not isinstance(text, str) or not text.strip()
                        or len(text) > MAX_PDF_TEXT_CHARS or type(page_count) is not int
                        or not 1 <= page_count <= MAX_PDF_PAGES):
                    return PdfTextResult(error_code="pdf_ipc_invalid")
                return PdfTextResult(text=text, page_count=page_count)
            except (OSError, ValueError, UnicodeError):
                return PdfTextResult(error_code="pdf_ipc_invalid")
    except OSError:
        return PdfTextResult(error_code="pdf_runtime_unavailable")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child":
        raise SystemExit(2)
    raise SystemExit(_child_main(sys.argv[2]))
