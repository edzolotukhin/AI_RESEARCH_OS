from __future__ import annotations

import unittest

from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.workflow import QuantitativeApprovalService
from domain.quantitative.workflow import QuantitativeApproval, QuantitativeApprovalDecision
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class P124CanonicalApprovalAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryQuantitativeStateRepository()
        self.digest = Sha256DigestProvider()
        self.state = QuantitativeStateService(
            repository=self.repository, digest_provider=self.digest
        )
        self.approvals = QuantitativeApprovalService(self.state, self.digest)

    def record(self, approval_id: str, decided_at: str, **changes) -> QuantitativeApproval:
        values = {
            "project_id": "project-1",
            "run_id": "run-1",
            "subject_type": "QC",
            "subject_id": "qc-record-1",
            "subject_fingerprint": "qc-fingerprint-1",
            "decision": QuantitativeApprovalDecision.APPROVED,
            "actor_id": "quality-manager",
            "rationale": "Reviewed and approved",
        }
        values.update(changes)
        return self.approvals.record(
            approval_id=approval_id, decided_at=decided_at, **values
        )

    def test_event_identity_and_time_do_not_change_canonical_authority(self):
        first = self.record("event-a", "2026-01-01T00:00:00+00:00")
        second = self.record("event-b", "2026-02-02T00:00:00+00:00")
        self.assertNotEqual(first.approval_id, second.approval_id)
        self.assertNotEqual(first.decided_at, second.decided_at)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_changed_qc_authority_changes_canonical_approval(self):
        first = self.record("event-a", "2026-01-01T00:00:00+00:00")
        second = self.record("event-b", "2026-01-01T00:00:00+00:00", subject_fingerprint="qc-fingerprint-2")
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_changed_decision_changes_canonical_approval(self):
        first = self.record("event-a", "2026-01-01T00:00:00+00:00")
        second = self.record("event-b", "2026-01-01T00:00:00+00:00", decision=QuantitativeApprovalDecision.REJECTED)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_persistence_round_trip_preserves_authority_and_audit_metadata(self):
        approval = self.record("event-a", "2026-01-01T00:00:00+00:00")
        loaded = self.state.load(approval.approval_id, project_id=approval.project_id, expected_type=QuantitativeApproval)
        self.assertEqual(approval, loaded)
        self.assertEqual("event-a", loaded.approval_id)
        self.assertEqual("2026-01-01T00:00:00+00:00", loaded.decided_at)
        self.assertEqual(approval.fingerprint, loaded.fingerprint)


if __name__ == "__main__":
    unittest.main()
