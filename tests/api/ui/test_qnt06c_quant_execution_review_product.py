from __future__ import annotations

import re
from pathlib import Path

from application.quantitative.workflow import QUANTITATIVE_SAFE_STATE_KEY
from domain.quantitative.analysis import StatisticalResult
from domain.quantitative.review import QuantitativeApprovedRevision, QuantitativeReview
from domain.quantitative.report import QuantitativeReportCompositionResult
from tests.api.helpers import ApiTestCase


class Qnt06cQuantExecutionReviewProductTests(ApiTestCase):
    def _owner(self) -> str:
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def _create_ready_design(self, key: str = "qnt06c") -> str:
        created = self.client.post(
            "/ui/quantitative/studies",
            data={"title": "QNT-06C", "description": "Known-answer product journey", "submission_key": key},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        uploaded = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={"dataset": (
                "known.sav", Path("tests/fixtures/quantitative/rb_reconciliation.sav").read_bytes(),
                "application/octet-stream",
            )},
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303, uploaded.text)
        self.assertEqual(self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc", follow_redirects=False,
        ).status_code, 303)
        data_page = self.client.get(f"/ui/quantitative/studies/{study_id}/data")
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', data_page.text)
        self.assertIsNotNone(fingerprint)
        approved_qc = self.client.post(
            f"/ui/quantitative/studies/{study_id}/qc-approval",
            data={"fingerprint": fingerprint.group(1), "decision": "APPROVED", "rationale": "Checked"},
            follow_redirects=False,
        )
        self.assertEqual(approved_qc.status_code, 303, approved_qc.text)
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self._owner())
        _, codebook = self.container.quantitative_ui_service._dataset(study)
        variable = next(item for item in codebook.variables if item.name == "categorical")
        group = next(item for item in codebook.variables if item.name == "region")
        configured = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design",
            data={
                "title": "Choice distribution", "research_question": "How is choice distributed?",
                "population": "Synthetic respondents", "procedure": "CROSS_TAB",
                "primary_variable_id": variable.variable_id,
                "group_variable_id": group.variable_id, "weighting_mode": "UNWEIGHTED",
            },
            follow_redirects=False,
        )
        self.assertEqual(configured.status_code, 303, configured.text)
        analysis_page = self.client.get(f"/ui/quantitative/studies/{study_id}/analysis")
        version = re.search(r'name="plan_version_id" value="([^"]+)"', analysis_page.text)
        plan_fingerprint = re.search(r'name="expected_fingerprint" value="([^"]+)"', analysis_page.text)
        self.assertIsNotNone(version)
        self.assertIsNotNone(plan_fingerprint)
        approved_design = self.client.post(
            f"/ui/quantitative/studies/{study_id}/design/approve",
            data={"plan_version_id": version.group(1), "expected_fingerprint": plan_fingerprint.group(1),
                  "rationale": "Exact design reviewed"},
            follow_redirects=False,
        )
        self.assertEqual(approved_design.status_code, 303, approved_design.text)
        return study_id

    def test_execute_requires_exact_approved_design(self):
        created = self.client.post(
            "/ui/quantitative/studies",
            data={"title": "No design", "description": "", "submission_key": "qnt06c-no-design"},
            follow_redirects=False,
        )
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        response = self.client.post(f"/ui/quantitative/studies/{study_id}/analysis/execute")
        self.assertEqual(response.status_code, 422)
        self.assertIn("approved current Analysis Design", response.text)

    def test_product_actions_complete_exact_results_review_and_revision(self):
        study_id = self._create_ready_design()
        analysis_page = self.client.get(f"/ui/quantitative/studies/{study_id}/analysis")
        self.assertIn("Виконати аналіз", analysis_page.text)

        executed = self.client.post(
            f"/ui/quantitative/studies/{study_id}/analysis/execute", follow_redirects=False,
        )
        self.assertEqual(executed.status_code, 303, executed.text)
        authority = self.container.quantitative_authority_product_service.projection(
            study_id, owner_id=self._owner(),
        )
        self.assertTrue(authority["semantic_authorization_required"])
        self.assertTrue(authority["semantic_authorization_token"])
        records = self.container.quantitative_ui_service.state.list_for_run(
            study_id, project_id=study_id,
        )
        self.assertTrue(any(isinstance(item, StatisticalResult) for item in records))

        stale = self.client.post(
            f"/ui/quantitative/studies/{study_id}/analysis/authorize-semantics",
            data={"expected_authority_fingerprint": "stale", "rationale": "wrong"},
        )
        self.assertEqual(stale.status_code, 422)
        self.assertIn("Stale semantic authorization authority", stale.text)

        completed = self.client.post(
            f"/ui/quantitative/studies/{study_id}/analysis/authorize-semantics",
            data={"expected_authority_fingerprint": authority["semantic_authorization_token"],
                  "rationale": "Exact Results and Findings reviewed"},
            follow_redirects=False,
        )
        self.assertEqual(
            completed.status_code, 303,
            f"{completed.text}\n{self.container.workflow_service.get_task_results(study_id)!r}",
        )
        study = self.container.quantitative_ui_service.get(study_id, owner_id=self._owner())
        self.assertEqual(study.state, "COMPLETED")
        records = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id, project_id=study.project_id,
        )
        record_types = tuple(type(item).__name__ for item in records)
        review = next((item for item in records if isinstance(item, QuantitativeReview)), None)
        report_record = next((item for item in records if isinstance(item, QuantitativeReportCompositionResult)), None)
        self.assertIsNotNone(review, (record_types, report_record, self.client.get(
            f"/ui/quantitative/studies/{study_id}/result.json").json()))
        revision = next((item for item in records if isinstance(item, QuantitativeApprovedRevision)), None)
        self.assertIsNotNone(revision, (record_types, review))
        self.assertEqual(revision.review_id, review.review_id)
        safe = self.container.workflow_service.get_task_results(study.run_id)[QUANTITATIVE_SAFE_STATE_KEY]
        self.assertEqual(safe["analysis_execution_mode"], "DESIGN_AWARE_EXECUTION")

        results_page = self.client.get(f"/ui/quantitative/studies/{study_id}/results")
        self.assertEqual(results_page.status_code, 200)
        self.assertIn("Перевірка цілісності", results_page.text)
        self.assertIn("Затверджена ревізія", results_page.text)
        self.assertNotIn("protected-dataset://", results_page.text)

    def test_legacy_run_cannot_use_canonical_execute_action(self):
        legacy = self.container.quantitative_ui_service.create_study(
            owner_id=self._owner(), title="Historical", description="",
            submission_key="qnt06c-legacy", canonical=False,
        )
        response = self.client.post(
            f"/ui/quantitative/studies/{legacy.study_id}/analysis/execute",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Historical Quant", response.text)
