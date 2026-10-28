from __future__ import annotations

import unittest

from application.deliverables.approved_delivery_provenance import (
    ApprovedDeliveryProvenance,
    provenance_from_storage,
    validate_storage_binding,
)


def _payload() -> dict[str, str | int]:
    return {
        "report_id": "report-1",
        "revision_number": 2,
        "authority_digest": "a" * 64,
        "presentation_digest": "b" * 64,
        "review_id": "review-1",
        "source_workflow_run_id": "source-run-1",
        "report_workflow_run_id": "report-run-1",
        "claim_set_digest": "c" * 64,
        "coverage_contract_digest": "d" * 64,
    }


class ApprovedDeliveryProvenanceTests(unittest.TestCase):
    def test_valid_construction_and_deterministic_round_trip(self) -> None:
        value = ApprovedDeliveryProvenance.from_dict(_payload())
        self.assertEqual(value.to_dict(), _payload())
        self.assertEqual(
            ApprovedDeliveryProvenance.from_dict(value.to_dict()),
            value,
        )
        self.assertEqual(list(value.to_dict()), list(_payload()))

    def test_unknown_and_missing_fields_are_rejected(self) -> None:
        unknown = {**_payload(), "extra": "x"}
        missing = _payload(); missing.pop("review_id")
        with self.assertRaisesRegex(ValueError, "fields"):
            ApprovedDeliveryProvenance.from_dict(unknown)
        with self.assertRaisesRegex(ValueError, "fields"):
            ApprovedDeliveryProvenance.from_dict(missing)

    def test_invalid_revision_and_identifiers_are_rejected(self) -> None:
        for revision in (0, -1, True, "1"):
            payload = {**_payload(), "revision_number": revision}
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                ApprovedDeliveryProvenance.from_dict(payload)
        for field in ("report_id", "review_id", "source_workflow_run_id",
                      "report_workflow_run_id"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                ApprovedDeliveryProvenance.from_dict({**_payload(), field: ""})

    def test_malformed_digests_are_rejected(self) -> None:
        for field in ("authority_digest", "presentation_digest", "claim_set_digest",
                      "coverage_contract_digest"):
            for value in ("a" * 63, "A" * 64, "z" * 64, 7):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ApprovedDeliveryProvenance.from_dict({**_payload(), field: value})

    def test_wrong_serialization_type_is_rejected(self) -> None:
        for value in (None, [], "payload"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ApprovedDeliveryProvenance.from_dict(value)

    def test_storage_round_trip_and_null_legacy_behavior(self) -> None:
        value = ApprovedDeliveryProvenance.from_dict(_payload())
        loaded = provenance_from_storage(
            report_id=value.report_id,
            revision_number=value.revision_number,
            authority_digest=value.authority_digest,
            presentation_digest=value.presentation_digest,
            review_id=value.review_id,
            source_workflow_run_id=value.source_workflow_run_id,
            report_workflow_run_id=value.report_workflow_run_id,
            claim_set_digest=value.claim_set_digest,
            coverage_contract_digest=value.coverage_contract_digest,
        )
        self.assertEqual(loaded, value)
        self.assertIsNone(provenance_from_storage(
            report_id="legacy-report", revision_number=None, authority_digest=None,
            presentation_digest=None, review_id=None, source_workflow_run_id=None,
            report_workflow_run_id="legacy-run", claim_set_digest=None,
            coverage_contract_digest=None,
        ))

    def test_partial_storage_and_split_brain_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "partial"):
            provenance_from_storage(
                report_id="report-1", revision_number=1, authority_digest=None,
                presentation_digest=None, review_id=None, source_workflow_run_id=None,
                report_workflow_run_id="run-1", claim_set_digest=None,
                coverage_contract_digest=None,
            )
        value = ApprovedDeliveryProvenance.from_dict(_payload())
        mismatches = {
            "report_id": "other-report",
            "report_workflow_run_id": "other-run",
            "revision_number": 3,
            "review_id": "other-review",
            "source_workflow_run_id": "other-source",
            "claim_set_digest": "e" * 64,
            "coverage_contract_digest": "f" * 64,
        }
        for field, invalid in mismatches.items():
            kwargs = {
                "report_id": value.report_id,
                "report_workflow_run_id": value.report_workflow_run_id,
                "revision_number": value.revision_number,
                "review_id": value.review_id,
                "source_workflow_run_id": value.source_workflow_run_id,
                "claim_set_digest": value.claim_set_digest,
                "coverage_contract_digest": value.coverage_contract_digest,
            }
            kwargs[field] = invalid
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "mismatch"):
                validate_storage_binding(value, **kwargs)


if __name__ == "__main__":
    unittest.main()
