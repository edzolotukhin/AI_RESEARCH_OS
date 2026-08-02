from __future__ import annotations

import hashlib
import re


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


DR06_RESEARCH_REPORT_TYPE = "research_report"


def compute_report_deduplication_key(
    *,
    workflow_run_id: str,
    report_type: str = DR06_RESEARCH_REPORT_TYPE,
    generation_method: str,
    revision_number: int = 1,
) -> str:
    """One immutable report revision per run/type/method/revision (DR-07)."""
    canonical = "|".join(
        [
            workflow_run_id,
            _normalize_text(report_type),
            generation_method,
            str(revision_number),
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_artifact_deduplication_key(
    *,
    workflow_run_id: str,
    artifact_type: str,
) -> str:
    """One canonical final artifact per run and artifact type (DR-06 v1)."""
    canonical = "|".join(
        [
            workflow_run_id,
            artifact_type,
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_content_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
