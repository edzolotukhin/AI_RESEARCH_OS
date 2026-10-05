from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from application.upload_security import (
    safe_upload_filename,
    validate_audio_signature,
    validate_docx,
    validate_quantitative_signature,
)
from tools.pilot_recovery import RecoveryError, ensure_empty, inventory, restic_base, run, required


def docx_with_members(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


class UploadSecurityTests(unittest.TestCase):
    def test_filename_is_metadata_not_a_path(self) -> None:
        self.assertEqual(safe_upload_filename("study.xlsx"), "study.xlsx")
        for value in ("../study.xlsx", "folder/study.xlsx", "C:\\study.xlsx", "bad\x00.txt"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_upload_filename(value)

    def test_docx_requires_bounded_safe_ooxml_structure(self) -> None:
        valid = docx_with_members({
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<w:document/>",
        })
        validate_docx(valid)
        for value in (
            b"not-a-zip",
            docx_with_members({"word/document.xml": b"<w:document/>"}),
            docx_with_members({
                "[Content_Types].xml": b"<Types/>",
                "word/document.xml": b"<w:document/>",
                "../escape": b"x",
            }),
        ):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                validate_docx(value)

    def test_quant_signatures_reject_extension_content_mismatch(self) -> None:
        validate_quantitative_signature(".xlsx", b"PK\x03\x04")
        validate_quantitative_signature(".sav", b"$FL2")
        with self.assertRaises(ValueError):
            validate_quantitative_signature(".xlsx", b"$FL2")
        with self.assertRaises(ValueError):
            validate_quantitative_signature(".sav", b"PK\x03\x04")

    def test_audio_signature_is_bounded_and_provider_free(self) -> None:
        validate_audio_signature("wav", b"RIFF\x04\x00\x00\x00WAVE")
        validate_audio_signature("mp3", b"ID3synthetic")
        with self.assertRaises(ValueError):
            validate_audio_signature("wav", b"RIFFnot-wave")


class RecoverySafetyTests(unittest.TestCase):
    def test_missing_secret_fails_without_value(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RecoveryError) as caught:
            required("RESTIC_PASSWORD_FILE")
        self.assertNotIn("password", str(caught.exception).casefold().replace("restic_password_file", ""))

    def test_restore_target_must_be_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_empty(root)
            (root / "authority").write_text("synthetic", encoding="utf-8")
            with self.assertRaises(RecoveryError):
                ensure_empty(root)

    def test_missing_required_storage_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RecoveryError):
                inventory(Path(temporary) / "missing")

    def test_missing_password_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "RESTIC_PASSWORD_FILE": str(Path(temporary) / "absent"),
            "RESTIC_REPOSITORY": str(Path(temporary) / "repository"),
        }, clear=True), self.assertRaises(RecoveryError):
            restic_base()

    @patch("tools.pilot_recovery.subprocess.run")
    def test_subprocess_failure_is_content_safe(self, execute: Mock) -> None:
        execute.return_value = Mock(returncode=1, stdout="", stderr="sensitive payload")
        with self.assertRaises(RecoveryError) as caught:
            run(["pg_dump", "synthetic-connection"])
        self.assertEqual(str(caught.exception), "pg_dump operation failed")
        self.assertNotIn("sensitive", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
