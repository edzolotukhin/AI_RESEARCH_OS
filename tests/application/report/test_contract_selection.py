import unittest

from application.report.contract_selection import (
    DESK_REPORT_CONTRACT_PIN,
    H2_REPORT_CONTRACT,
    H3_REPORT_CONTRACT,
    pin_desk_report_contract,
    resolve_pinned_desk_report_contract,
)


class DeskReportContractSelectionTests(unittest.TestCase):
    def test_pin_round_trips_and_is_not_overwritten(self):
        stored = pin_desk_report_contract({"other": {"ok": True}}, H3_REPORT_CONTRACT)
        self.assertEqual(stored[DESK_REPORT_CONTRACT_PIN], H3_REPORT_CONTRACT)
        self.assertEqual(
            resolve_pinned_desk_report_contract(stored, fallback=H2_REPORT_CONTRACT),
            H3_REPORT_CONTRACT,
        )
        with self.assertRaises(ValueError):
            pin_desk_report_contract(stored, H2_REPORT_CONTRACT)

    def test_unknown_contract_fails_closed(self):
        with self.assertRaises(ValueError):
            pin_desk_report_contract({}, "desk_unknown_v1")
        with self.assertRaises(ValueError):
            resolve_pinned_desk_report_contract(
                {DESK_REPORT_CONTRACT_PIN: "desk_unknown_v1"},
            )


if __name__ == "__main__":
    unittest.main()
