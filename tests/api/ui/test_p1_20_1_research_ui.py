"""P1-20.1 minimal inspectable Research UI offline acceptance."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tests.api.helpers import ApiTestCase, drain_background_runs
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF

REPO_ROOT = Path(__file__).resolve().parents[3]
UI_PATHS = [
    REPO_ROOT / "api" / "routers" / "ui_research.py",
    REPO_ROOT / "api" / "ui" / "research_facade.py",
    REPO_ROOT / "api" / "static" / "research.js",
]


def _detail_fixture(
    *,
    outcome: str,
    malicious: str | None = None,
) -> dict[str, Any]:
    payload = malicious or "<script>alert(1)</script>"
    return {
        "run_id": "ui-fixture-run",
        "research_id": "ui-fixture-run",
        "project_id": "ui-project",
        "workflow_status": "completed" if outcome != "EXECUTION_FAILED" else "failed",
        "outcome": outcome,
        "readiness": {"available": True, "ready_for_analysis": outcome == "APPROVED"},
        "termination_reason": None,
        "limitations": ["Sample limitation"],
        "budget_usage": {"available": True, "partial": False},
        "source_summary": {"count": 1, "ids": ["src-1"], "items": []},
        "evidence_summary": {"count": 1, "ids": ["ev-1"], "items": []},
        "finding_summary": {"count": 1, "ids": ["f-1"], "items": []},
        "insight_summary": {"count": 0, "ids": [], "items": []},
        "latest_report": None,
        "latest_review": None,
        "artifact_status": {"count": 0, "approved_count": 0, "rejected_count": 0, "draft_count": 0},
        "provenance_summary": {
            "report_id": "rep-1" if outcome in {"APPROVED", "QUALITY_REJECTED"} else None,
            "finding_ids": ["f-1"],
            "insight_ids": [],
            "evidence_ids": ["ev-1"],
            "source_ids": ["src-1"],
            "links": [
                {
                    "finding_id": "f-1",
                    "insight_id": None,
                    "evidence_id": "ev-1",
                    "source_id": "src-1",
                },
            ],
            "unresolved_refs": [],
        },
        "detail": {
            "sources": [
                {
                    "id": "src-1",
                    "title": f"Title {payload}",
                    "publisher": "Publisher",
                    "url": "https://example.com/safe",
                    "canonical_url": "https://example.com/safe",
                    "source_type": "web",
                    "content_type": "text/html",
                    "retrieval_status": "acquired",
                    "truncated": False,
                    "evidence_count": 1,
                },
                {
                    "id": "src-unsafe",
                    "title": "Unsafe",
                    "publisher": "",
                    "url": "javascript:alert(1)",
                    "canonical_url": "javascript:alert(1)",
                    "source_type": "web",
                    "content_type": "",
                    "retrieval_status": "acquired",
                    "truncated": False,
                    "evidence_count": 0,
                },
            ],
            "evidence": [
                {
                    "id": "ev-1",
                    "statement": {"value": f"Statement {payload}", "truncated": False, "original_length": 10},
                    "source_excerpt": {
                        "value": f"Excerpt {payload}",
                        "truncated": True,
                        "original_length": 1200,
                    },
                    "source_id": "src-1",
                    "evidence_type": "direct_excerpt",
                    "research_question_refs": [],
                    "information_need_refs": [],
                },
            ],
            "findings": [
                {
                    "id": "f-1",
                    "statement": {"value": "Finding statement", "truncated": False, "original_length": 10},
                    "rationale": {"value": "Rationale", "truncated": False, "original_length": 5},
                    "evidence_refs": ["ev-1"],
                    "research_question_refs": [],
                    "information_need_refs": [],
                },
            ],
            "insights": [],
            "report": (
                {
                    "id": "rep-1",
                    "title": "Report title",
                    "executive_summary": {
                        "value": f"Summary {payload}",
                        "truncated": False,
                        "original_length": 20,
                    },
                    "limitations": ["Report limitation"],
                    "revision_number": 1,
                    "previous_report_id": None,
                    "sections": [
                        {
                            "id": "sec-1",
                            "title": "Section",
                            "content": {"value": f"Body {payload}", "truncated": False, "original_length": 8},
                            "finding_refs": ["f-1"],
                            "insight_refs": [],
                            "evidence_refs": ["ev-1"],
                            "citation_ids": [],
                        },
                    ],
                    "citation_registry": {},
                }
                if outcome in {"APPROVED", "QUALITY_REJECTED"}
                else None
            ),
            "review": (
                {
                    "id": "rev-1",
                    "report_id": "rep-1",
                    "artifact_id": None,
                    "verdict": "approve" if outcome == "APPROVED" else "reject",
                    "review_attempt": 1,
                    "previous_report_id": None,
                    "summary": {"value": "Review summary", "truncated": False, "original_length": 10},
                    "issues": [
                        {
                            "id": "issue-1",
                            "issue_type": "missing_citation",
                            "severity": "major",
                            "message": {"value": f"Issue {payload}", "truncated": False, "original_length": 8},
                            "report_section_id": "sec-1",
                            "finding_refs": [],
                            "insight_refs": [],
                            "evidence_refs": [],
                            "source_refs": [],
                            "research_question_refs": [],
                            "suggested_action": "",
                        },
                    ],
                    "quality_dimensions": [],
                }
                if outcome in {"APPROVED", "QUALITY_REJECTED"}
                else None
            ),
            "truncation": {
                "collection_truncated": True,
                "total_counts": {"evidence": 243, "sources": 10},
                "report_truncated": False,
                "section_truncated_ids": [],
            },
        },
    }


class ResearchUiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ui = self._raw_client

    def _mock_facade(
        self,
        *,
        status: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
        detail_error: Exception | None = None,
    ) -> MagicMock:
        facade = MagicMock()
        facade.get_status.return_value = status or {
            "research_id": "ui-fixture-run",
            "execution_status": "TERMINAL",
            "phase": "COMPLETED",
            "product_outcome": "APPROVED",
            "result_available": True,
            "workflow_status": "completed",
        }
        if detail_error is not None:
            facade.get_result_detail.side_effect = detail_error
        else:
            facade.get_result_detail.return_value = detail or _detail_fixture(outcome="APPROVED")
        return facade

    def test_case_01_new_form_renders(self) -> None:
        response = self.ui.get("/ui/research/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Start new research", response.content)
        self.assertIn(b'business_question', response.content)

    def test_case_02_valid_brief_submission(self) -> None:
        response = self.ui.post(
            "/ui/research",
            data={
                "title": BRIEF["title"],
                "business_question": BRIEF["business_question"],
                "objectives": "\n".join(BRIEF["objectives"]),
                "geography": ", ".join(BRIEF["geography"]),
                "timeframe": BRIEF["timeframe"],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/ui/research/"))

    def test_case_03_double_submit_blocked_by_disabled_button(self) -> None:
        html = self.ui.get("/ui/research/new").text
        self.assertIn('id="start-research-btn"', html)
        self.assertIn("Submitting", self.ui.get("/static/research.js").text)

    def test_case_04_redirect_after_submit(self) -> None:
        response = self.ui.post(
            "/ui/research",
            data={
                "title": BRIEF["title"],
                "business_question": BRIEF["business_question"],
                "objectives": "\n".join(BRIEF["objectives"]),
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        research_id = response.headers["location"].split("/")[-1]
        self.assertTrue(research_id)

    def test_cases_05_10_phase_labels_present(self) -> None:
        for phase in (
            "PLANNING",
            "RESEARCHING",
            "EVALUATING",
            "ANALYZING",
            "WRITING",
            "REVIEWING",
        ):
            with self.subTest(phase=phase):
                facade = self._mock_facade(
                    status={
                        "research_id": "ui-fixture-run",
                        "execution_status": "RUNNING",
                        "phase": phase,
                        "product_outcome": None,
                        "result_available": False,
                        "workflow_status": "running",
                    },
                )
                with patch(
                    "api.routers.ui_research.build_research_ui_facade",
                    return_value=facade,
                ):
                    response = self.ui.get("/ui/research/ui-fixture-run")
                self.assertEqual(response.status_code, 200)
                self.assertIn(phase.encode(), response.content)

    def test_case_11_no_fake_progress_percentage(self) -> None:
        facade = self._mock_facade(
            status={
                "research_id": "ui-fixture-run",
                "execution_status": "RUNNING",
                "phase": "RESEARCHING",
                "product_outcome": None,
                "result_available": False,
                "workflow_status": "running",
            },
        )
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertNotRegex(html, r"\b\d{1,3}%\b")

    def test_case_12_terminal_detail_consumed(self) -> None:
        facade = self._mock_facade(detail=_detail_fixture(outcome="APPROVED"))
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.ui.get("/ui/research/ui-fixture-run")
        self.assertEqual(response.status_code, 200)
        facade.get_result_detail.assert_called_once()

    def test_case_13_approved_renders_report_and_findings(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Approved", html)
        self.assertIn("Report title", html)
        self.assertIn("Finding statement", html)

    def test_case_14_not_ready_message(self) -> None:
        detail = _detail_fixture(outcome="NOT_READY")
        detail["detail"]["report"] = None
        detail["detail"]["findings"] = []
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=detail),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Not ready for analysis", html)
        self.assertIn("not sufficient", html)
        self.assertNotIn("System failed", html)

    def test_case_15_quality_rejected_review_issues(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="QUALITY_REJECTED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Quality not approved", html)
        self.assertIn("Not approved", html)
        self.assertIn("Major issues", html)
        self.assertIn("missing_citation", html)

    def test_case_16_execution_failed_safe(self) -> None:
        detail = _detail_fixture(outcome="EXECUTION_FAILED")
        detail["detail"]["report"] = None
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=detail),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Execution failed", html)
        self.assertNotIn("Traceback", html)

    def test_cases_17_19_provenance_chain(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("View evidence", html)
        self.assertIn("Excerpt", html)
        self.assertIn("Publisher", html)

    def test_case_20_safe_external_link_attributes(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('target="_blank"', html)

    def test_case_21_unsafe_url_not_clickable(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("javascript:alert(1)", html)
        self.assertNotIn('href="javascript:alert(1)"', html)

    def test_case_22_report_sections_render(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Section", html)

    def test_case_24_limitations_render(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("Sample limitation", html)

    def test_case_25_truncation_metadata_visible(self) -> None:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=_detail_fixture(outcome="APPROVED")),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("truncated", html.lower())
        self.assertIn("243", html)

    def test_cases_26_27_deep_link_refresh(self) -> None:
        facade = self._mock_facade(
            status={
                "research_id": "ui-fixture-run",
                "execution_status": "RUNNING",
                "phase": "PLANNING",
                "product_outcome": None,
                "result_available": False,
                "workflow_status": "running",
            },
        )
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            first = self.ui.get("/ui/research/ui-fixture-run")
            second = self.ui.get("/ui/research/ui-fixture-run")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_case_28_unknown_research_404(self) -> None:
        from application.persistence.exceptions import EntityNotFoundError

        facade = MagicMock()
        facade.get_status.side_effect = EntityNotFoundError("missing")
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.ui.get("/ui/research/missing-run")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"not found", response.content.lower())

    def test_case_29_detail_409_json(self) -> None:
        from application.query.research_run_result import ResearchRunResultProjectionError

        facade = MagicMock()
        facade.get_result_detail.side_effect = ResearchRunResultProjectionError("not terminal")
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.ui.get("/ui/research/ui-fixture-run/detail.json")
        self.assertEqual(response.status_code, 409)

    def test_case_32_empty_evidence_handled(self) -> None:
        detail = _detail_fixture(outcome="APPROVED")
        detail["detail"]["evidence"] = []
        detail["detail"]["findings"] = []
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=detail),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("No findings available", html)

    def test_case_34_no_report_handled(self) -> None:
        detail = _detail_fixture(outcome="APPROVED")
        detail["detail"]["report"] = None
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(detail=detail),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertIn("No report available", html)

    def test_cases_35_37_xss_escaped(self) -> None:
        payload = '<script>alert(1)</script>'
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(
                detail=_detail_fixture(outcome="APPROVED", malicious=payload),
            ),
        ):
            html = self.ui.get("/ui/research/ui-fixture-run").text
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_case_38_public_facade_only(self) -> None:
        forbidden = (
            "/workflow-runs",
            "/reports/",
            "/evidence/",
            "/sources/",
            "/reviews/",
            "/tasks/",
        )
        combined = ""
        for path in UI_PATHS:
            combined += path.read_text(encoding="utf-8")
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_case_39_no_workflow_endpoint_calls_in_js(self) -> None:
        js = (REPO_ROOT / "api" / "static" / "research.js").read_text(encoding="utf-8")
        self.assertNotIn("workflow-runs", js)
        self.assertIn("/ui/research/", js)

    def test_case_41_narrow_viewport_css(self) -> None:
        css = (REPO_ROOT / "api" / "static" / "research.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 720px)", css)

    def test_case_42_form_labels(self) -> None:
        html = self.ui.get("/ui/research/new").text
        self.assertIn('for="business_question"', html)

    def test_case_43_keyboard_controls(self) -> None:
        html = self.ui.get("/ui/research/new").text
        self.assertIn("<button", html)
        self.assertIn('type="submit"', html)

    def test_ui_root_redirect(self) -> None:
        response = self.ui.get("/ui", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/ui/research/new")

    def test_status_json_endpoint(self) -> None:
        facade = self._mock_facade()
        with patch("api.routers.ui_research.build_research_ui_facade", return_value=facade):
            response = self.ui.get("/ui/research/ui-fixture-run/status.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["execution_status"], "TERMINAL")

    def test_no_bearer_token_in_templates_or_js(self) -> None:
        templates_root = REPO_ROOT / "api" / "templates"
        combined = ""
        for path in templates_root.rglob("*.html"):
            combined += path.read_text(encoding="utf-8")
        combined += (REPO_ROOT / "api" / "static" / "research.js").read_text(encoding="utf-8")
        self.assertNotIn("Bearer ", combined)
        self.assertNotIn("_test_api_key_plaintext", combined)


if __name__ == "__main__":
    unittest.main()
