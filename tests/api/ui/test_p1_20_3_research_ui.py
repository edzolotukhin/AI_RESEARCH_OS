"""P1-20.3 internal pilot hardening offline acceptance."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from api.ui.presentation import (
    UNKNOWN_LIMITATION_LABEL,
    humanize_limitation,
)
from tests.api.helpers import ApiTestCase
from tests.api.ui.test_p1_20_1_research_ui import _detail_fixture

REPO_ROOT = Path(__file__).resolve().parents[3]


def _not_ready_detail(**overrides: Any) -> dict[str, Any]:
    payload = _detail_fixture(outcome="NOT_READY")
    payload["termination_reason"] = "evidence_remediation_budget_exhausted"
    payload["limitations"] = [
        "evidence_remediation_budget_exhausted",
        "insufficient_research",
    ]
    payload["detail"]["report"] = None
    payload["detail"]["review"] = None
    payload["detail"]["findings"] = []
    payload["detail"]["insights"] = []
    payload["readiness"] = {
        "available": True,
        "ready_for_analysis": False,
        "research_outcome": "insufficient_research",
        "termination_reason": "evidence_remediation_budget_exhausted",
    }
    payload.update(overrides)
    return payload


class ResearchUiHardeningTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ui = self._raw_client

    def _mock_facade(self, *, status=None, detail=None) -> MagicMock:
        facade = MagicMock()
        facade.get_status.return_value = status or {
            "research_id": "ui-fixture-run",
            "execution_status": "TERMINAL",
            "phase": "COMPLETED",
            "product_outcome": "NOT_READY",
            "result_available": True,
            "workflow_status": "completed",
        }
        facade.get_result_detail.return_value = detail or _not_ready_detail()
        return facade

    def _html(self, *, status=None, detail=None) -> str:
        with patch(
            "api.routers.ui_research.build_research_ui_facade",
            return_value=self._mock_facade(status=status, detail=detail),
        ):
            response = self.ui.get("/ui/research/ui-fixture-run")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_case_01_compose_passes_ui_credential(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_block = compose.split("worker:")[0]
        self.assertIn("UI_INTERNAL_API_KEY: ${UI_INTERNAL_API_KEY:-}", api_block)
        self.assertIn("AI_RESEARCH_OS_API_KEY: ${AI_RESEARCH_OS_API_KEY:-}", api_block)

    def test_case_02_and_36_no_credential_in_browser_payload(self) -> None:
        html = self.ui.get("/ui/research/new").text
        js = (REPO_ROOT / "api" / "static" / "research.js").read_text(encoding="utf-8")
        combined = html + js
        self.assertNotIn("UI_INTERNAL_API_KEY", combined)
        self.assertNotIn("AI_RESEARCH_OS_API_KEY", combined)
        self.assertNotIn("Bearer ", combined)
        self.assertNotIn("_test_api_key_plaintext", combined)

    def test_cases_10_13_outcome_semantics_unchanged(self) -> None:
        for outcome, needle in (
            ("NOT_READY", "Not ready for analysis"),
            ("APPROVED", "Approved"),
            ("QUALITY_REJECTED", "Quality not approved"),
            ("EXECUTION_FAILED", "Execution failed"),
        ):
            with self.subTest(outcome=outcome):
                detail = _detail_fixture(outcome=outcome)
                if outcome == "NOT_READY":
                    detail = _not_ready_detail()
                html = self._html(
                    status={
                        "research_id": "ui-fixture-run",
                        "execution_status": "TERMINAL",
                        "phase": "COMPLETED",
                        "product_outcome": outcome,
                        "result_available": True,
                        "workflow_status": "completed",
                    },
                    detail=detail,
                )
                self.assertIn(needle, html)
                self.assertIn("Research result", html)

    def test_cases_14_19_not_ready_evidence_and_source(self) -> None:
        html = self._html()
        self.assertIn("Evidence (", html)
        self.assertIn("Statement", html)
        self.assertIn("Excerpt", html)
        self.assertIn("Publisher", html)
        self.assertIn("Title", html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn("https://example.com/safe", html)

    def test_case_20_unsafe_url_not_clickable(self) -> None:
        html = self._html()
        self.assertIn("javascript:alert(1)", html)
        self.assertNotIn('href="javascript:alert(1)"', html)

    def test_case_21_missing_source_ref_safe(self) -> None:
        detail = _not_ready_detail()
        detail["detail"]["evidence"] = [
            {
                "id": "ev-orphan",
                "statement": {"value": "Orphan statement", "truncated": False, "original_length": 10},
                "source_excerpt": {"value": "Orphan excerpt", "truncated": False, "original_length": 10},
                "source_id": "missing-src",
                "evidence_type": "direct_excerpt",
                "research_question_refs": [],
                "information_need_refs": [],
            },
        ]
        html = self._html(detail=detail)
        self.assertIn("Orphan statement", html)
        self.assertIn("Source details are not available", html)

    def test_case_22_evidence_truncation_visible(self) -> None:
        detail = _not_ready_detail()
        detail["detail"]["truncation"] = {
            "collection_truncated": True,
            "total_counts": {"evidence": 58, "sources": 34},
            "report_truncated": False,
            "section_truncated_ids": [],
        }
        html = self._html(detail=detail)
        self.assertIn("Showing 1 of 58 evidence items.", html)

    def test_cases_23_25_no_fabricated_downstream(self) -> None:
        html = self._html()
        self.assertNotIn("Finding statement", html)
        self.assertNotIn("Report title", html)
        self.assertNotIn("Quality review", html)
        self.assertNotIn("No findings available", html)

    def test_cases_26_30_human_readable_limitations(self) -> None:
        self.assertIn("not sufficient", humanize_limitation("insufficient_research"))
        self.assertIn(
            "evidence-gathering limit",
            humanize_limitation("evidence_remediation_budget_exhausted"),
        )
        self.assertIn(
            "reserved for downstream",
            humanize_limitation("downstream_reserve_exhausted"),
        )
        self.assertEqual(
            humanize_limitation("totally_unknown_code"),
            UNKNOWN_LIMITATION_LABEL,
        )
        html = self._html()
        self.assertIn("evidence-gathering limit", html)
        self.assertIn("not sufficient to support a reliable analysis", html)
        limitations = html.split('id="limitations-panel"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("evidence_remediation_budget_exhausted", limitations)
        self.assertNotIn("insufficient_research", limitations)

    def test_cases_31_32_page_titles(self) -> None:
        progress = self._html(
            status={
                "research_id": "ui-fixture-run",
                "execution_status": "RUNNING",
                "phase": "RESEARCHING",
                "product_outcome": None,
                "result_available": False,
                "workflow_status": "running",
            },
            detail=None,
        )
        self.assertIn("Research progress", progress)
        self.assertNotIn("Research result", progress)
        terminal = self._html()
        self.assertIn("Research result", terminal)

    def test_cases_33_35_xss_escaped_on_not_ready(self) -> None:
        payload = "<script>alert(1)</script>"
        html = self._html(detail=_not_ready_detail())
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_case_37_no_content_text_leakage(self) -> None:
        html = self._html()
        self.assertNotIn("content_text", html)
        for path in (REPO_ROOT / "api" / "templates" / "research").glob("*.html"):
            self.assertNotIn("content_text", path.read_text(encoding="utf-8"))

    def test_case_38_no_traceback(self) -> None:
        html = self._html()
        self.assertNotIn("Traceback", html)
        self.assertNotIn("Exception", html)

    def test_case_39_deep_link_terminal(self) -> None:
        first = self._html()
        second = self._html()
        self.assertIn("Not ready for analysis", first)
        self.assertIn("Not ready for analysis", second)

    def test_case_40_polling_unchanged(self) -> None:
        js = (REPO_ROOT / "api" / "static" / "research.js").read_text(encoding="utf-8")
        self.assertIn("3000", js)
        self.assertIn("TERMINAL", js)

    def test_case_43_public_facade_only(self) -> None:
        forbidden = ("/workflow-runs", "/reports/", "/evidence/", "/sources/", "/reviews/", "/tasks/")
        combined = ""
        for path in (
            REPO_ROOT / "api" / "routers" / "ui_research.py",
            REPO_ROOT / "api" / "ui" / "research_facade.py",
            REPO_ROOT / "api" / "ui" / "presentation.py",
            REPO_ROOT / "api" / "static" / "research.js",
        ):
            combined += path.read_text(encoding="utf-8")
        for token in forbidden:
            self.assertNotIn(token, combined)

    def test_case_47_p1_20_2_not_ready_replay_inspectable(self) -> None:
        html = self._html()
        self.assertIn("Not ready for analysis", html)
        self.assertIn("evidence-gathering limit", html)
        self.assertIn("Evidence (", html)
        self.assertIn("Sources (", html)
        self.assertIn("source-excerpt", html)


if __name__ == "__main__":
    unittest.main()
