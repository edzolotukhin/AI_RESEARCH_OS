"""Dispatch Desk report execution from the durable run contract pin."""

from __future__ import annotations

from application.report.contract_selection import (
    H2_REPORT_CONTRACT,
    H3_REPORT_CONTRACT,
    resolve_pinned_desk_report_contract,
)


class DeskReportContractRouter:
    def __init__(self, *, h2, h3) -> None:
        self._services = {H2_REPORT_CONTRACT: h2, H3_REPORT_CONTRACT: h3}

    def write_for_context(self, context):
        pin = context.read_shared("_desk_report_contract_v1")
        contract = resolve_pinned_desk_report_contract(
            {"_desk_report_contract_v1": pin},
            # Runs predating durable pinning are historical H2-compatible
            # executions; never reinterpret them as the new H3 default.
            fallback=H2_REPORT_CONTRACT,
        )
        service = self._services.get(contract)
        if service is None:
            raise ValueError(f"Unsupported persisted Desk report contract: {contract}")
        return service.write_for_context(context)
