import unittest
from types import SimpleNamespace

from application.report.claim_set_policy import (
    ClaimSetContractError,
    validate_homogeneous_append,
    validate_homogeneous_claim_set,
)
from domain.reports.report_claim import H3_REPORT_CLAIM_VERSION, REPORT_CLAIM_V2_VERSION
from tests.application.report.test_report_claim_contract import ReportClaimContractTests
from tests.application.report.test_report_claim_v2_contract import ReportClaimV2ContractTests


class ClaimSetPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        v1_fixture = ReportClaimContractTests()
        v1_fixture.setUp()
        self.v1 = v1_fixture.claim()
        v2_fixture = ReportClaimV2ContractTests()
        self.v2 = v2_fixture.claim()
        self.h3 = SimpleNamespace(contract_version=H3_REPORT_CLAIM_VERSION)

    def test_homogeneous_versions_are_accepted(self) -> None:
        self.assertEqual(validate_homogeneous_claim_set((self.v1,)), self.v1.contract_version)
        self.assertEqual(validate_homogeneous_claim_set((self.v2,)), REPORT_CLAIM_V2_VERSION)
        self.assertEqual(validate_homogeneous_claim_set((self.h3,)), H3_REPORT_CLAIM_VERSION)

    def test_all_mixed_versions_are_rejected(self) -> None:
        for claims in ((self.v1, self.v2), (self.v1, self.h3), (self.v2, self.h3)):
            with self.assertRaises(ClaimSetContractError):
                validate_homogeneous_claim_set(claims)

    def test_empty_set_has_no_verification_status(self) -> None:
        self.assertIsNone(validate_homogeneous_claim_set(()))

    def test_sequential_append_changes_are_rejected(self) -> None:
        for first, second in ((self.v1, self.v2), (self.v2, self.v1)):
            self.assertEqual(validate_homogeneous_append((), (first,)), first.contract_version)
            with self.assertRaises(ClaimSetContractError):
                validate_homogeneous_append((first.contract_version,), (second,))


if __name__ == "__main__":
    unittest.main()
