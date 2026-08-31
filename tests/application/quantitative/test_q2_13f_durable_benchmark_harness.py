from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from application.quantitative.execution_diagnostics import (
    SEMANTIC_LEDGER_KEY,
    SemanticCallRecorder,
)
from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.workflow import QUANTITATIVE_SAFE_STATE_KEY
from domain.project import Project
from domain.quantitative.research_question_coverage import (
    QuantitativeResearchQuestionCoverageAssessmentVersion,
    QuantitativeResearchQuestionCoverageRunManifest,
    ResearchQuestionAssessmentStatus,
    ResearchQuestionCoverageLifecycle,
)
from domain.quantitative.workflow import QuantitativeTerminalOutcome, QuantitativeTerminalResult
from infrastructure.persistence.quantitative_research_question_coverage_repository import (
    QLQuantitativeResearchQuestionCoverageRepository,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from runtime.workflow_context import WorkflowContext
from tests.helpers.quantitative_benchmark_harness import (
    BenchmarkJournal,
    DurableBenchmarkRepositoryBundle,
    durable_diagnostics,
    is_phase_a_freeze,
    resolve_workflow_produced_rh,
)
from tests.helpers.workflow_run_builder import make_workflow_run


class Q213FDurableBenchmarkHarnessTests(unittest.TestCase):
    project_id = "benchmark-project"
    run_id = "benchmark-run"

    def _seed(self, root: Path, *, failed_qj: bool = False):
        bundle = DurableBenchmarkRepositoryBundle.open(root)
        project = Project(id=self.project_id, name="Offline benchmark")
        project.owner_principal_id = "benchmark-owner"
        bundle.project_repository.create(project)
        run = make_workflow_run(run_id=self.run_id)
        run.ready()
        run.start()
        run.complete()
        bundle.workflow_run_repository.create(run, project_id=self.project_id)

        context = WorkflowContext(
            workflow_run=run,
            project=project,
            current_task=None,
            shared_state={QUANTITATIVE_SAFE_STATE_KEY: {}},
        )
        recorder = SemanticCallRecorder(context, None)
        for stage in ("QI", "QJ", "QK"):
            call_id = recorder.planned(
                stage=stage,
                provider="offline-fake",
                model="deterministic",
                input_fingerprint=(stage.lower() * 64)[:64],
            )
            recorder.dispatched(call_id)
            if stage == "QJ" and failed_qj:
                recorder.failed(call_id, RuntimeError("offline failure"), after_dispatch=True)
                break
            recorder.returned(call_id, (stage * 64)[:64])
            recorder.completed(call_id, (stage * 64)[:64])

        state = QuantitativeStateService(
            repository=bundle.quantitative_state_repository,
            digest_provider=Sha256DigestProvider(),
        )
        assessment = QuantitativeResearchQuestionCoverageAssessmentVersion(
            "rh-assessment", "rh-version", 1, self.project_id, self.run_id,
            "QUANTITATIVE", "design-v1", "d" * 64, "rq-1", "Bounded RQ",
            ("objective-1",), ("requirement-1",), (), (), (),
            ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW,
            (), (), "rh-1", None, ResearchQuestionCoverageLifecycle.IN_REVIEW,
            None, "a" * 64, "2026-08-31T00:00:00Z", "production-workflow",
        )
        state.persist(
            assessment, record_id=assessment.version_id,
            project_id=self.project_id, run_id=self.run_id, accepted=True,
        )
        manifest = QuantitativeResearchQuestionCoverageRunManifest(
            "rh-manifest", self.project_id, self.run_id, "design-v1", "d" * 64,
            ((assessment.version_id, assessment.fingerprint),),
            "IN_REVIEW", "rh-1", "m" * 64,
        )
        state.persist(
            manifest, record_id=manifest.manifest_id,
            project_id=self.project_id, run_id=self.run_id, accepted=True,
        )
        terminal = QuantitativeTerminalResult(
            "terminal", self.project_id, self.run_id, "QUANTITATIVE",
            "dataset-v1", "x" * 64, "APPROVED", ("dataset-v1",),
            None, None, None, (), 1, 0, 1, 0, "report", "ACCEPTED", (),
            "COMPLETED", QuantitativeTerminalOutcome.COMPLETED, "t" * 64,
            "UNWEIGHTED", "d" * 64,
        )
        state.persist(
            terminal, record_id="terminal-record", project_id=self.project_id,
            run_id=self.run_id, accepted=True,
        )
        results = {
            QUANTITATIVE_SAFE_STATE_KEY: {
                "rq_coverage_manifest_record_id": manifest.manifest_id,
                "terminal_result_record_id": "terminal-record",
            },
            SEMANTIC_LEDGER_KEY: context.shared_state[SEMANTIC_LEDGER_KEY],
        }
        bundle.workflow_run_repository.save(run, task_results=results)
        return bundle, assessment, manifest, terminal

    def test_restart_recovers_terminal_ledger_and_workflow_produced_rh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, expected_assessment, expected_manifest, expected_terminal = self._seed(root)
            restarted = DurableBenchmarkRepositoryBundle.open(root)
            state = QuantitativeStateService(
                repository=restarted.quantitative_state_repository,
                digest_provider=Sha256DigestProvider(),
            )
            rh = QLQuantitativeResearchQuestionCoverageRepository(state)
            spy = Mock(wraps=rh)
            manifest, assessments = resolve_workflow_produced_rh(
                workflow_repository=restarted.workflow_run_repository,
                rh_repository=spy,
                project_id=self.project_id,
                run_id=self.run_id,
            )
            self.assertEqual(expected_manifest, manifest)
            self.assertEqual((expected_assessment,), assessments)
            self.assertFalse(spy.save_assessment.called)
            self.assertFalse(spy.save_run_manifest.called)
            safe = restarted.workflow_run_repository.get_task_results(self.run_id)[QUANTITATIVE_SAFE_STATE_KEY]
            self.assertEqual(
                expected_terminal,
                state.load(safe["terminal_result_record_id"], project_id=self.project_id),
            )
            projection = durable_diagnostics(
                workflow_repository=restarted.workflow_run_repository,
                project_id=self.project_id,
                run_id=self.run_id,
            )
            self.assertEqual({"QI": 1, "QJ": 1, "QK": 1}, projection["dispatched"])
            self.assertEqual(
                ("COMPLETED", "COMPLETED", "COMPLETED"),
                tuple(item["status"] for item in projection["calls"]),
            )

            # Reentry resolves the same immutable authority without a write.
            again = resolve_workflow_produced_rh(
                workflow_repository=restarted.workflow_run_repository,
                rh_repository=spy,
                project_id=self.project_id,
                run_id=self.run_id,
            )
            self.assertEqual((manifest, assessments), again)
            self.assertFalse(spy.save_assessment.called)

    def test_failed_semantic_lifecycle_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root, failed_qj=True)
            restarted = DurableBenchmarkRepositoryBundle.open(root)
            projection = durable_diagnostics(
                workflow_repository=restarted.workflow_run_repository,
                project_id=self.project_id,
                run_id=self.run_id,
            )
            self.assertEqual({"QI": 1, "QJ": 1, "QK": 0}, projection["dispatched"])
            self.assertEqual("FAILED_AFTER_DISPATCH", projection["calls"][-1]["status"])

    def test_post_workflow_failure_writes_bounded_non_freeze_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "r6-failure.json"
            journal = BenchmarkJournal(
                "Q2-13A-R6", {"dataset": "hash"}, path,
                project_id=self.project_id, run_id=self.run_id,
                phase="POST_WORKFLOW", terminal_result_record_id="terminal-record",
                last_successful_authority="RH", ppt_content_reads=0,
            )
            error = RuntimeError("raw respondent payload must not persist")
            with self.assertRaisesRegex(RuntimeError, "respondent"):
                journal.run(lambda: (_ for _ in ()).throw(error), lambda: {"total_dispatched": 3})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("BENCHMARK_FAILURE", payload["artifact_kind"])
            self.assertEqual("[redacted benchmark diagnostic]", payload["sanitized_message"])
            self.assertEqual(0, payload["blindness"]["ppt_content_reads"])
            self.assertFalse(is_phase_a_freeze(path))

    def test_activation_failure_is_journaled_and_artifact_failure_does_not_mask_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "activation-failure.json"
            journal = BenchmarkJournal("Q2-13A-R6", {}, path, phase="ACTIVATION")
            primary = LookupError("activation stopped")
            with self.assertRaises(LookupError) as raised:
                journal.run(lambda: (_ for _ in ()).throw(primary))
            self.assertIs(primary, raised.exception)
            self.assertTrue(path.exists())

            impossible = root / "directory-target"
            impossible.mkdir()
            broken = BenchmarkJournal("Q2-13A-R6", {}, impossible, phase="POST_WORKFLOW")
            original = RuntimeError("primary remains primary")
            with self.assertRaises(RuntimeError) as raised:
                broken.run(lambda: (_ for _ in ()).throw(original))
            self.assertIs(original, raised.exception)

    def test_only_explicit_success_artifact_unlocks_phase_b(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure = root / "failure.json"
            failure.write_text(json.dumps({"artifact_kind": "BENCHMARK_FAILURE"}), encoding="utf-8")
            self.assertFalse(is_phase_a_freeze(failure))
            success = root / "freeze.json"
            success.write_text(json.dumps({
                "artifact_kind": "PHASE_A_FREEZE",
                "phase_a_complete": True,
                "freeze_fingerprint": "f" * 64,
            }), encoding="utf-8")
            self.assertTrue(is_phase_a_freeze(success))


if __name__ == "__main__":
    unittest.main()
