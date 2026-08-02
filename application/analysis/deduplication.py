from __future__ import annotations

import hashlib
import re


def _normalize_statement(statement: str) -> str:
    collapsed = re.sub(r"\s+", " ", statement.strip().lower())
    return collapsed


def compute_finding_deduplication_key(
    *,
    workflow_run_id: str,
    statement: str,
    evidence_refs: tuple[str, ...],
) -> str:
    canonical = "|".join(
        [
            workflow_run_id,
            _normalize_statement(statement),
            ",".join(sorted(evidence_refs)),
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_insight_deduplication_key(
    *,
    workflow_run_id: str,
    statement: str,
    finding_refs: tuple[str, ...],
) -> str:
    canonical = "|".join(
        [
            workflow_run_id,
            _normalize_statement(statement),
            ",".join(sorted(finding_refs)),
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
