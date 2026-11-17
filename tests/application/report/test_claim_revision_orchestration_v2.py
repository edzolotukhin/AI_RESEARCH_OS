from __future__ import annotations

from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import Mock, patch

from application.report.claim_revision_orchestration_v2 import create_report_claim_v2_successor
from domain.reports.report import Report


def make_report(report_id: str, revision: int, *, previous: str | None = None) -> Report:
    return Report(
        id=report_id, project_id="project", workflow_run_id="run",
        research_design_id="design", title="Report", language="en",
        sections=(), executive_summary="", limitations=(),
        created_at="2026-01-01T00:00:00Z", generation_method="test",
        finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
        deduplication_key=report_id, revision_number=revision,
        previous_report_id=previous,
    )


class TransactionFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def repeatable_read_transaction(self):
        self.events.append("begin")
        try:
            yield self
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


class RevisionRepositories:
    def __init__(self, parent: Report, events: list[str]) -> None:
        self.parent, self.events = parent, events
        self.report_repository = Mock()
        self.report_repository.lock_revision.side_effect = self.lock_revision
        self.report_repository.allocate_successor.side_effect = self.allocate_successor
        self.report_claim_repository = Mock()
        self.report_claim_repository.create_with_report.side_effect = self.persist

    def lock_revision(self, report_id: str, *, expected_revision: int) -> Report:
        self.events.append("lock_parent")
        if report_id != self.parent.id or expected_revision != self.parent.revision_number:
            raise ValueError("stale parent")
        return self.parent

    def allocate_successor(self, *_args, **_kwargs):
        self.events.append("allocate")
        return self.parent

    def persist(self, *_args, **_kwargs):
        self.events.append("persist")
        return 1

    def all(self) -> dict:
        return {
            "report_repository": self.report_repository,
            "report_claim_repository": self.report_claim_repository,
            "finding_repository": Mock(), "insight_repository": Mock(),
            "evidence_repository": Mock(), "source_repository": Mock(),
            "workflow_run_repository": Mock(), "workflow_template_repository": Mock(),
        }


class ClaimRevisionOrchestrationV2Tests(TestCase):
    def setUp(self) -> None:
        self.events: list[str] = []
        self.parent = make_report("parent", 1)
        self.successor = make_report("successor", 2, previous="parent")
        self.factory = TransactionFactory(self.events)
        self.repositories = RevisionRepositories(self.parent, self.events)
        self.snapshot = Mock()
        self.snapshot.to_revision_inputs.return_value = (Mock(), Mock())

    def invoke(self, successor: Report | None = None) -> tuple:
        def verify(*_args, **_kwargs):
            self.events.append("verifier")
            return self.snapshot

        def rebuild(*_args, **_kwargs):
            self.events.append("builder")
            return Mock()

        with patch("application.report.claim_revision_orchestration_v2.verify_persisted_claim_v2_snapshot_write_transaction", side_effect=verify), patch("application.report.claim_revision_orchestration_v2.rebuild_report_claim_v2", side_effect=rebuild):
            return create_report_claim_v2_successor(
                session_factory=self.factory, parent_report_id=self.parent.id,
                parent_claim_id="parent-claim", successor_report=successor or self.successor,
                validated_at="2026-01-01T00:00:00Z", **self.repositories.all(),
            )

    def test_successful_call_sequence_shares_one_transaction(self) -> None:
        self.invoke()
        self.assertEqual(self.events, ["begin", "lock_parent", "verifier", "builder", "allocate", "persist", "commit"])

    def test_incompatible_successor_scope_fails_before_verification(self) -> None:
        invalid = make_report("successor", 2, previous="parent")
        invalid.project_id = "foreign-project"
        with self.assertRaises(ValueError):
            self.invoke(invalid)
        self.assertEqual(self.events, ["begin", "lock_parent", "rollback"])

    def test_verifier_failure_prevents_allocation_and_persistence(self) -> None:
        with patch("application.report.claim_revision_orchestration_v2.verify_persisted_claim_v2_snapshot_write_transaction", side_effect=ValueError("stale")):
            with self.assertRaises(ValueError):
                create_report_claim_v2_successor(
                    session_factory=self.factory, parent_report_id=self.parent.id,
                    parent_claim_id="parent-claim", successor_report=self.successor,
                    validated_at="2026-01-01T00:00:00Z", **self.repositories.all(),
                )
        self.assertEqual(self.events, ["begin", "lock_parent", "rollback"])

    def test_persistence_failure_rolls_back_after_allocation(self) -> None:
        def fail_persist(*_args, **_kwargs):
            self.events.append("persist")
            raise RuntimeError("write failed")

        self.repositories.report_claim_repository.create_with_report.side_effect = fail_persist
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(self.events, ["begin", "lock_parent", "verifier", "builder", "allocate", "persist", "rollback"])


if __name__ == "__main__":
    import unittest
    unittest.main()
