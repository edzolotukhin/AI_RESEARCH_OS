"""Package B: bounded downstream failure-localization qualification."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from unittest.mock import Mock

from application.deliverables.approved_delivery_provenance import (
    ApprovedDeliveryProvenance,
    provenance_failure_code,
    provenance_mismatch_diagnostics,
)
from application.deliverables.service import DeliverableFinalizationError
from application.executors.finalization_executor import FinalizationExecutor
from application.report.editorial_composer import (
    EditorialComposer,
    EditorialCompositionError,
    LlmEditorialProposalProvider,
)
from domain.ai.llm_response import LLMResponse
import tests.application.review.test_presentation_review_lifecycle as review_lifecycle


def _provenance() -> ApprovedDeliveryProvenance:
    return ApprovedDeliveryProvenance(
        report_id="report-1", revision_number=2,
        authority_digest="a" * 64, presentation_digest="b" * 64,
        review_id="review-1", source_workflow_run_id="source-run",
        report_workflow_run_id="report-run", claim_set_digest="c" * 64,
        coverage_contract_digest="d" * 64,
    )


class _Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return self.responses.pop(0)


class DownstreamObservabilityGateTests(unittest.TestCase):
    def test_each_provenance_field_is_localized_without_unbounded_content(self):
        expected = _provenance()
        replacements = {
            "report_id": "report-2", "revision_number": 3,
            "authority_digest": "1" * 64, "presentation_digest": "2" * 64,
            "review_id": "review-2", "source_workflow_run_id": "source-other",
            "report_workflow_run_id": "report-other", "claim_set_digest": "3" * 64,
            "coverage_contract_digest": "4" * 64,
        }
        for field, value in replacements.items():
            actual = replace(expected, **{field: value})
            diagnostic = provenance_mismatch_diagnostics(
                component="qualification", expected=expected, actual=actual,
            )
            with self.subTest(field=field):
                self.assertEqual([field], diagnostic["mismatch_fields"])
                self.assertEqual(value, diagnostic["actual"][field])
                self.assertEqual(getattr(expected, field), diagnostic["expected"][field])
                self.assertLessEqual(len(repr(diagnostic)), 512)
                self.assertIn(field, provenance_failure_code(
                    component="qualification", expected=expected, actual=actual,
                ))

    def test_real_editorial_adapter_keeps_initial_and_repair_parse_metadata_separate(self):
        from tests.application.report.test_editorial_composer import EditorialComposerTests
        fixture = EditorialComposerTests(); fixture.setUp()
        responses = (
            LLMResponse(content="not json", finish_reason="stop", output_tokens=2, max_output_tokens=100),
            LLMResponse(content="[]", finish_reason="length", output_tokens=100, max_output_tokens=100,
                        incomplete_reason="max_output_tokens"),
        )
        client = _Client(*responses)
        with self.assertRaises(EditorialCompositionError) as captured:
            EditorialComposer(LlmEditorialProposalProvider(client)).compose(
                report_id="report-1", revision_number=1, source_report_id="report-1",
                authority_digest="authority", catalog=fixture.catalog,
            )
        attempts = captured.exception.diagnostics["attempts"]
        self.assertEqual(2, client.calls)
        self.assertEqual(("initial", "repair"), tuple(item["attempt"] for item in attempts))
        self.assertEqual("invalid_json", attempts[0]["parse_failure_category"])
        self.assertEqual("non_object_root", attempts[1]["parse_failure_category"])
        self.assertEqual("list", attempts[1]["decoded_root_type"])
        self.assertEqual("length", attempts[1]["finish_reason"])
        self.assertEqual("max_output_tokens", attempts[1]["incomplete_reason"])
        self.assertNotIn("not json", repr(attempts))

    def test_real_editorial_adapter_localizes_typed_schema_failure_after_decode(self):
        from tests.application.report.test_editorial_composer import EditorialComposerTests
        fixture = EditorialComposerTests(); fixture.setUp()
        client = _Client(*(
            LLMResponse(content=json.dumps({}), finish_reason="stop", output_tokens=2, max_output_tokens=100)
            for _ in range(2)
        ))
        with self.assertRaises(EditorialCompositionError) as captured:
            EditorialComposer(LlmEditorialProposalProvider(client)).compose(
                report_id="report-1", revision_number=1, source_report_id="report-1",
                authority_digest="authority", catalog=fixture.catalog,
            )
        self.assertEqual(
            ["proposal_schema", "proposal_schema"],
            [item["validation_codes"][0] for item in captured.exception.diagnostics["attempts"]],
        )
        for attempt in captured.exception.diagnostics["attempts"]:
            self.assertEqual("dict", attempt["decoded_root_type"])
            self.assertEqual("stop", attempt["finish_reason"])
            self.assertTrue(attempt["content_present"])
            self.assertGreater(attempt["content_length"], 0)

    def test_real_editorial_adapter_records_completed_response_without_content(self):
        from tests.application.report.test_editorial_composer import EditorialComposerTests
        fixture = EditorialComposerTests(); fixture.setUp()
        content = json.dumps(fixture.valid, ensure_ascii=False)
        client = _Client(LLMResponse(
            content=content, finish_reason="stop", output_tokens=10, max_output_tokens=100,
        ))
        result = EditorialComposer(LlmEditorialProposalProvider(client)).compose(
            report_id="report-1", revision_number=1, source_report_id="report-1",
            authority_digest="authority", catalog=fixture.catalog,
        )
        attempt = result.diagnostics["attempts"][0]
        self.assertEqual("valid", attempt["status"])
        self.assertEqual("stop", attempt["finish_reason"])
        self.assertEqual("dict", attempt["decoded_root_type"])
        self.assertEqual(len(content), attempt["content_length"])
        self.assertNotIn(content, repr(attempt))

    def test_review_revision_metadata_localizes_target_and_exact_revision(self):
        fixture = review_lifecycle.PresentationReviewLifecycleTests()
        _, _, service, reviews, context, reports, _ = fixture.fixture(revise_once=True)
        summary = service.review_for_context(context)
        records = sorted(reviews.list_for_project(context.project.id), key=lambda item: item.review_attempt)
        self.assertEqual(("revise", "approve"), tuple(item.verdict.value for item in records))
        self.assertEqual((1, 2), tuple(item.metadata["reviewed_revision_number"] for item in records))
        self.assertTrue(records[0].metadata["issue_targets"])
        self.assertEqual(summary.report_id, records[1].metadata["approved_report_id"])
        self.assertEqual(2, records[1].metadata["approved_revision_number"])

    def test_finalization_executor_persists_bounded_component_and_field_diagnostics(self):
        expected = _provenance()
        actual = replace(expected, presentation_digest="9" * 64)
        diagnostics = provenance_mismatch_diagnostics(
            component="pptx", expected=expected, actual=actual,
        )
        error = DeliverableFinalizationError(
            "finalization_failed", "provenance_mismatch_pptx_presentation_digest",
            diagnostics=diagnostics,
        )
        finalizer = Mock()
        finalizer.finalize_approved_review.side_effect = error
        context = Mock()
        context.project.id = "project-1"
        state = {
            "review": {"verdict": "approve", "report_id": "report-1", "review_id": "review-1"},
        }
        context.read_shared.side_effect = lambda key: state.get(key)
        context.write_shared.side_effect = lambda key, value: state.__setitem__(key, value)
        with self.assertRaises(DeliverableFinalizationError):
            FinalizationExecutor(finalizer).run(context)
        persisted = state["desk_deliverable_finalization"]
        self.assertEqual("pptx", persisted["diagnostics"]["component"])
        self.assertEqual(["presentation_digest"], persisted["diagnostics"]["mismatch_fields"])
        self.assertNotIn("provider", repr(persisted).casefold())

    def test_failed_finalization_snapshot_durably_keeps_only_bounded_envelope(self):
        from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
        from tests.application.runtime.test_workflow_runtime_persister_audit import (
            WorkflowRuntimePersisterAuditOrderingTests,
        )
        fixture = WorkflowRuntimePersisterAuditOrderingTests(); fixture.setUp()
        task = fixture.workflow_run.tasks[0]
        task.definition_id = "task-finalization"
        task.executor_id = "finalization"
        fixture.context.current_task = task
        task.ready(); task.start(); task.fail()
        diagnostic = {
            "status": "finalization_failed",
            "failure_code": "provenance_mismatch_pdf_presentation_digest",
            "report_id": "report-1", "review_id": "review-1",
            "diagnostics": {
                "category": "approved_delivery_provenance_mismatch",
                "component": "pdf", "mismatch_fields": ["presentation_digest"],
                "expected": {"presentation_digest": "a" * 64},
                "actual": {"presentation_digest": "b" * 64},
            },
        }
        fixture.context.shared_state = {
            "desk_deliverable_finalization": diagnostic,
            "unrelated": {"raw": "must-not-persist"},
        }
        saved = {}
        fixture.workflow_service.save_workflow_run.side_effect = (
            lambda run, expected_version, **kwargs:
                saved.update(kwargs["task_results"]) or expected_version + 1
        )
        persister = WorkflowRuntimePersister(
            workflow_service=fixture.workflow_service, audit=fixture.audit,
            run_id=fixture.workflow_run.id, initial_version=0,
        )
        persister.on_task_finished(fixture.context, error=RuntimeError("failed"))
        snapshot = saved[task.id]["shared_state"]
        self.assertEqual(diagnostic, snapshot["desk_deliverable_finalization"])
        self.assertNotIn("unrelated", snapshot)


if __name__ == "__main__":
    unittest.main()
