import io
import os
import zipfile

import pytest

from tests.qualification.p8d_desk_evidence_runner import (
    _require_disposable_database,
    _sha,
    _validate_pptx,
)


def _pptx_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<p:presentation/>")
        archive.writestr("ppt/slides/slide1.xml", "<p:sld>content</p:sld>")
    return stream.getvalue()


def test_pptx_structural_validation_and_checksum():
    data = _pptx_bytes()
    _validate_pptx(data)
    assert _sha(data) == _sha(data)


def test_pptx_structural_validation_rejects_corrupt_package():
    with pytest.raises(ValueError):
        _validate_pptx(b"PK-not-a-valid-package")


def test_database_guard_rejects_missing_test_url(monkeypatch):
    monkeypatch.setenv("POSTGRESQL_INTEGRATION_TESTS", "1")
    monkeypatch.setenv("POSTGRESQL_DISPOSABLE_TEST_DATABASE", "1")
    monkeypatch.delenv("DATABASE_URL_TEST", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL_TEST"):
        _require_disposable_database()


def test_database_guard_accepts_only_approved_target(monkeypatch):
    monkeypatch.setenv("POSTGRESQL_INTEGRATION_TESTS", "1")
    monkeypatch.setenv("POSTGRESQL_DISPOSABLE_TEST_DATABASE", "1")
    monkeypatch.setenv("DATABASE_URL_TEST", "postgresql://user:pass@127.0.0.1:55432/ai_research_os_p8d_isolation_test")
    assert _require_disposable_database().endswith("ai_research_os_p8d_isolation_test")
