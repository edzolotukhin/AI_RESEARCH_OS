from __future__ import annotations

import hashlib


def compute_review_deduplication_key(
    *,
    workflow_run_id: str,
    report_id: str,
    review_attempt: int,
) -> str:
    canonical = "|".join(
        [
            workflow_run_id,
            report_id,
            str(review_attempt),
        ],
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
