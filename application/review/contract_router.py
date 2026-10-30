from __future__ import annotations

from application.report.contract_selection import (
    DESK_REPORT_CONTRACT_PIN, H2_REPORT_CONTRACT, H3_REPORT_CONTRACT,
)


class DeskReviewContractRouter:
    """Route Review by the persisted execution pin, never by prose."""

    def __init__(self, *, h2, h3) -> None:
        self._services = {H2_REPORT_CONTRACT: h2, H3_REPORT_CONTRACT: h3}

    def review_for_context(self, context):
        pin = context.read_shared(DESK_REPORT_CONTRACT_PIN)
        if pin is None:
            return self._services[H2_REPORT_CONTRACT].review_for_context(context)
        if pin not in self._services:
            raise ValueError(f"Unsupported persisted Desk Review contract: {pin!r}")
        return self._services[pin].review_for_context(context)
