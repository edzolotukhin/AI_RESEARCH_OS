import json
from pathlib import Path

from tests.qualification.p8d_pptx_diagnostic import MAX_DIAGNOSTIC, render_payload


def _document():
    return {
        "project_id": "diagnostic-project", "method": "DESK", "run_id": "diagnostic-run",
        "study_id": None, "source_id": "diagnostic-report", "source_version": "revision-1",
        "status": "Схвалено", "title": "Diagnostic report", "summary": "Synthetic summary",
        "sections": [{"title": "Section", "paragraphs": ["Supported synthetic text"], "citations": []}],
        "limitations": ["Synthetic diagnostic only"], "tables": [], "citation_registry": [],
        "links": [], "unavailable": [], "created_at": None, "revision_number": 1,
        "previous_report_id": None, "charts": [], "approval_review_id": None,
        "approval_decision": None, "source_run_id": None, "claim_set_digest": None,
        "coverage_contract_digest": None, "approved_delivery_provenance": None,
        "canonical_delivery": None,
    }


def test_real_renderer_accepts_minimal_document():
    result = render_payload(_document())
    assert result.ok
    assert result.category == "ok"


def test_diagnostic_category_and_bounded_output():
    payload = _document()
    payload["method"] = "UNSUPPORTED_METHOD"
    result = render_payload(payload)
    assert not result.ok
    assert result.category == "input_validation"
    assert len(result.stderr) <= MAX_DIAGNOSTIC
    assert "UNSUPPORTED_METHOD" not in result.stderr


def test_oversized_payload_fails_before_node_and_does_not_leak_content():
    payload = _document()
    payload["summary"] = "SECRET_TEST_CONTENT_" + "x" * 900_000
    result = render_payload(payload)
    assert result.category == "input_validation"
    assert "SECRET_TEST_CONTENT" not in result.stderr


def test_invalid_document_is_classified_without_payload_logging():
    payload = _document()
    payload["project_id"] = ""
    result = render_payload(payload)
    assert not result.ok
    assert result.category == "input_validation"
    assert "diagnostic-project" not in result.stderr
