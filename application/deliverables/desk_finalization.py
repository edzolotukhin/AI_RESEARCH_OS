"""Exact structured-Desk approval and finalization provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from application.report.coverage_contract import CONTRACT_KEY


STRUCTURED_REPORT_CONTRACT = "desk_report_claim_v1"
MAX_PPTX_ATTEMPTS = 3


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def claim_set_digest(claims) -> str:
    """Digest the exact immutable claim set independent of repository ordering."""
    return _digest([item.to_dict() for item in sorted(claims, key=lambda item: item.claim_id)])


def coverage_contract_digest(report) -> str:
    return _digest(report.metadata.get(CONTRACT_KEY))


@dataclass(frozen=True)
class DeskFinalizationAuthority:
    project_id: str
    report_run_id: str
    source_run_id: str
    design_id: str
    report_id: str
    report_revision: int
    review_id: str
    claim_set_digest: str
    coverage_contract_digest: str

    @property
    def source_version(self) -> str:
        return (
            f"revision-{self.report_revision}-review-{self.review_id}-approve-"
            f"claims-{self.claim_set_digest[:16]}-coverage-{self.coverage_contract_digest[:16]}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "report_run_id": self.report_run_id,
            "source_run_id": self.source_run_id,
            "design_id": self.design_id,
            "report_id": self.report_id,
            "report_revision": self.report_revision,
            "review_id": self.review_id,
            "claim_set_digest": self.claim_set_digest,
            "coverage_contract_digest": self.coverage_contract_digest,
        }
