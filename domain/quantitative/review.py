"""Immutable, source-bound decisions for the quantitative report lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from domain.reviews.review_verdict import ReviewVerdict


@dataclass(frozen=True)
class QuantitativeReview:
    review_id: str
    project_id: str
    run_id: str
    method_version: str
    dataset_record_id: str
    dataset_fingerprint: str
    analysis_manifest_record_id: str
    analysis_manifest_fingerprint: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    insight_generation_record_id: str
    insight_generation_fingerprint: str
    report_composition_record_id: str
    report_composition_fingerprint: str
    verdict: ReviewVerdict
    issues: tuple[str, ...]
    fingerprint: str
    analysis_plan_fingerprint: str = ""
    weighting_authority_fingerprint: str = ""


@dataclass(frozen=True)
class QuantitativeApprovedRevision:
    revision_id: str
    project_id: str
    run_id: str
    method_version: str
    review_id: str
    review_fingerprint: str
    report_id: str
    report_validation_fingerprint: str
    dataset_record_id: str
    dataset_fingerprint: str
    analysis_manifest_record_id: str
    analysis_manifest_fingerprint: str
    finding_generation_record_id: str
    finding_generation_fingerprint: str
    insight_generation_record_id: str
    insight_generation_fingerprint: str
    fingerprint: str
    analysis_plan_fingerprint: str = ""
    weighting_authority_fingerprint: str = ""
