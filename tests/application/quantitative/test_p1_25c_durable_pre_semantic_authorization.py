from __future__ import annotations

import unittest

from application.quantitative.state_persistence import QuantitativeStateService
from application.quantitative.workflow import (
    SEMANTIC_AUTHORITY_FINGERPRINT_KEY,
    SEMANTIC_PIPELINE_BOUNDARY,
    QuantitativeApprovalRequired,
    QuantitativeApprovalService,
    QuantitativeWorkflowError,
)
from domain.quantitative.workflow import (
    QuantitativeSemanticAuthorization,
    QuantitativeSemanticAuthorizationConsumption,
    QuantitativeSemanticAuthorizationState,
)
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import (
    InMemoryQuantitativeStateRepository,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class P125CDurablePreSemanticAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryQuantitativeStateRepository()
        self.digest = Sha256DigestProvider()
        self.state = QuantitativeStateService(
            repository=self.repository, digest_provider=self.digest
        )
        self.approvals = QuantitativeApprovalService(self.state, self.digest)
        self.safe = {
            "dataset_version_id": "dataset-v1",
            "dataset_fingerprint": "dataset-fp",
            "codebook_version_id": "codebook-v1",
            "analysis_manifest_record_id": "analysis-v1",
        }

    def _fingerprint(self, *, project_id: str = "project-1", run_id: str = "run-1") -> str:
        return self.approvals.semantic_authority_fingerprint(
            project_id=project_id, run_id=run_id, safe_state=self.safe
        )

    def _grant(self, *, project_id: str = "project-1", run_id: str = "run-1"):
        return self.approvals.grant_semantic_pipeline(
            project_id=project_id,
            run_id=run_id,
            quantitative_authority_fingerprint=self._fingerprint(
                project_id=project_id, run_id=run_id
            ),
            actor_id="reviewer-1",
            authorized_at="2026-09-14T10:00:00+00:00",
            rationale="approved semantic execution",
        )

    def test_missing_wrong_project_and_wrong_run_fail_closed(self):
        with self.assertRaises(QuantitativeApprovalRequired):
            self.approvals.require_and_consume_semantic_pipeline(
                project_id="project-1", run_id="run-1", safe_state=self.safe
            )
        self._grant(project_id="other-project", run_id="run-1")
        self._grant(project_id="project-1", run_id="other-run")
        with self.assertRaises(QuantitativeApprovalRequired):
            self.approvals.require_and_consume_semantic_pipeline(
                project_id="project-1", run_id="run-1", safe_state=self.safe
            )

    def test_stale_declared_authority_fails_closed(self):
        stale = dict(self.safe, **{SEMANTIC_AUTHORITY_FINGERPRINT_KEY: "stale"})
        with self.assertRaisesRegex(QuantitativeWorkflowError, "stale"):
            self.approvals.require_and_consume_semantic_pipeline(
                project_id="project-1", run_id="run-1", safe_state=stale
            )

    def test_malformed_authorization_state_fails_closed(self):
        fingerprint = self._fingerprint()
        malformed = QuantitativeSemanticAuthorization(
            authorization_id="malformed",
            project_id="project-1",
            run_id="run-1",
            boundary=SEMANTIC_PIPELINE_BOUNDARY,
            quantitative_authority_fingerprint=fingerprint,
            state=QuantitativeSemanticAuthorizationState.CONSUMED,
            actor_id="reviewer-1",
            authorized_at="2026-09-14T10:00:00+00:00",
            rationale="invalid grant state",
            fingerprint="malformed-fingerprint",
        )
        self.state.persist(
            malformed,
            record_id=malformed.authorization_id,
            project_id="project-1",
            run_id="run-1",
        )
        with self.assertRaises(QuantitativeApprovalRequired):
            self.approvals.require_and_consume_semantic_pipeline(
                project_id="project-1", run_id="run-1", safe_state=self.safe
            )

    def test_authorization_is_idempotent_and_preserves_audit_metadata(self):
        first = self._grant()
        second = self.approvals.grant_semantic_pipeline(
            project_id="project-1",
            run_id="run-1",
            quantitative_authority_fingerprint=self._fingerprint(),
            actor_id="reviewer-1",
            authorized_at="2026-09-14T11:00:00+00:00",
            rationale="approved semantic execution",
        )
        self.assertEqual(first, second)
        self.assertEqual(first.authorized_at, "2026-09-14T10:00:00+00:00")
        restored = QuantitativeStateService(
            repository=self.repository, digest_provider=self.digest
        ).load(
            first.authorization_id,
            project_id="project-1",
            expected_type=QuantitativeSemanticAuthorization,
        )
        self.assertEqual(restored, first)

    def test_consumption_is_persisted_before_duplicate_is_rejected(self):
        grant = self._grant()
        safe = dict(self.safe, **{SEMANTIC_AUTHORITY_FINGERPRINT_KEY: self._fingerprint()})
        consumed = self.approvals.require_and_consume_semantic_pipeline(
            project_id="project-1", run_id="run-1", safe_state=safe
        )
        self.assertEqual(consumed.authorization_id, grant.authorization_id)
        self.assertIs(consumed.state, QuantitativeSemanticAuthorizationState.CONSUMED)
        restarted = QuantitativeApprovalService(
            QuantitativeStateService(repository=self.repository, digest_provider=self.digest),
            self.digest,
        )
        persisted = restarted.state_service.load(
            consumed.consumption_id,
            project_id="project-1",
            expected_type=QuantitativeSemanticAuthorizationConsumption,
        )
        self.assertEqual(persisted.fingerprint, consumed.fingerprint)
        with self.assertRaisesRegex(QuantitativeWorkflowError, "already consumed"):
            restarted.require_and_consume_semantic_pipeline(
                project_id="project-1", run_id="run-1", safe_state=safe
            )


if __name__ == "__main__":
    unittest.main()