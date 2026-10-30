import unittest
from types import SimpleNamespace

from application.report.contract_router import DeskReportContractRouter


class _Service:
    def __init__(self, value):
        self.value = value

    def write_for_context(self, context):
        return self.value


class DeskReportContractRouterTests(unittest.TestCase):
    def test_dispatches_by_persisted_pin_not_worker_default(self):
        router = DeskReportContractRouter(
            h2=_Service("h2"), h3=_Service("h3"),
        )
        self.assertEqual(
            router.write_for_context(SimpleNamespace(
                read_shared=lambda key: "desk_h3_structural_claim_v1",
            )),
            "h3",
        )
        self.assertEqual(
            router.write_for_context(SimpleNamespace(
                read_shared=lambda key: "desk_report_claim_v1",
            )),
            "h2",
        )

    def test_missing_pin_uses_historical_h2_compatibility(self):
        router = DeskReportContractRouter(h2=_Service("h2"), h3=_Service("h3"))
        self.assertEqual(
            router.write_for_context(SimpleNamespace(read_shared=lambda key: None)),
            "h2",
        )

    def test_unknown_pin_fails_closed(self):
        router = DeskReportContractRouter(h2=_Service("h2"), h3=_Service("h3"))
        with self.assertRaises(ValueError):
            router.write_for_context(SimpleNamespace(
                read_shared=lambda key: "desk_unknown_v1",
            ))


if __name__ == "__main__":
    unittest.main()
