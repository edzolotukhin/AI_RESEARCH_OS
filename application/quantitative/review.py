"""Deterministic final review of one immutable CMF Quant source package."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import NAMESPACE_URL, uuid5

from application.methods.quantitative.finding_authority import CanonicalQuantFindingSupportValidator
from application.methods.quantitative.insight_integrity import CanonicalQuantInsightValidator
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from application.quantitative.report_composition import QuantitativeReportValidator
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from domain.quantitative.dataset import DatasetVersion
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.report import (
    QuantitativeReportCompositionResult, QuantitativeReportValidationStatus,
)
from domain.quantitative.review import QuantitativeApprovedRevision, QuantitativeReview
from domain.quantitative.workflow import QuantitativeAnalysisManifest
from domain.reviews.review_verdict import ReviewVerdict
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType


class QuantitativeReviewService:
    """Recheck canonical sources before committing an approval decision.

    The report, Findings and Insights are never repaired here. A rejected
    decision is recorded against the exact package and has no revision.
    """

    def __init__(self, *, state_service, digest_provider, review_repository):
        self.state = state_service
        self.digest = digest_provider
        self.reviews = review_repository

    def review(self, *, project_id, run_id, state):
        keys = (
            "dataset_record_id", "analysis_manifest_record_id",
            "finding_generation_record_id", "insight_generation_record_id",
            "report_composition_record_id",
        )
        if any(not state.get(key) for key in keys):
            raise QuantitativeAnalysisError("Quant Review package is incomplete")
        for key in keys:
            self.state.require_record_scope(state[key], project_id=project_id, run_id=run_id)
        dataset = self.state.load(state["dataset_record_id"], project_id=project_id,
                                  expected_type=DatasetVersion)
        manifest = self.state.load(state["analysis_manifest_record_id"], project_id=project_id,
                                   expected_type=QuantitativeAnalysisManifest)
        findings = self.state.load(state["finding_generation_record_id"], project_id=project_id,
                                   expected_type=QuantitativeFindingGenerationResult)
        insights = self.state.load(state["insight_generation_record_id"], project_id=project_id,
                                   expected_type=QuantitativeInsightGenerationResult)
        composition = self.state.load(state["report_composition_record_id"], project_id=project_id,
                                      expected_type=QuantitativeReportCompositionResult)
        sources = (dataset.dataset_fingerprint, manifest.fingerprint,
                   findings.generation_fingerprint, insights.generation_fingerprint,
                   composition.composition_fingerprint)
        identity = (("dataset_record_id", "dataset_fingerprint"),
                    ("analysis_manifest_record_id", "analysis_manifest_fingerprint"),
                    ("finding_generation_record_id", "finding_generation_fingerprint"),
                    ("insight_generation_record_id", "insight_generation_fingerprint"),
                    ("report_composition_record_id", "report_composition_fingerprint"))
        binding = tuple((state[key], fingerprint) for (key, _), fingerprint in zip(identity, sources))
        issues = []
        try:
            self._validate(project_id=project_id, run_id=run_id, state=state,
                           dataset=dataset, manifest=manifest, findings=findings,
                           insights=insights, composition=composition)
        except (QuantitativeAnalysisError, ValueError) as exc:
            issues.append(str(exc))
        verdict = ReviewVerdict.REVISE if issues else ReviewVerdict.APPROVE
        payload = {"contract": "QNT04_REVIEW_V1", "project": project_id,
                   "run": run_id, "method": "QUANTITATIVE/1", "bindings": binding,
                   "plan": state.get("analysis_plan_fingerprint", ""),
                   "weighting": state.get("weighting_authority_fingerprint", ""),
                   "verdict": verdict.value, "issues": tuple(issues)}
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        review = QuantitativeReview(
            str(uuid5(NAMESPACE_URL, f"quant-review:{run_id}:{fingerprint}")),
            project_id, run_id,
            "QUANTITATIVE/1", state["dataset_record_id"], sources[0],
            state["analysis_manifest_record_id"], sources[1],
            state["finding_generation_record_id"], sources[2],
            state["insight_generation_record_id"], sources[3],
            state["report_composition_record_id"], sources[4],
            verdict, tuple(issues), fingerprint,
            state.get("analysis_plan_fingerprint", ""),
            state.get("weighting_authority_fingerprint", ""),
        )
        self._persist_once(review, review.review_id, project_id, run_id,
                           dataset.version_id, verdict is ReviewVerdict.APPROVE)
        self._persist_shared_review(review, state=state, report=composition.accepted_report)
        if verdict is not ReviewVerdict.APPROVE:
            return review, None
        report = composition.accepted_report
        revision_payload = {"contract": "QNT04_APPROVED_REVISION_V1",
                            "review": (review.review_id, review.fingerprint),
                            "report": (report.report_id, report.validation_fingerprint),
                            "bindings": binding, "project": project_id, "run": run_id,
                            "method": "QUANTITATIVE/1",
                            "plan": state.get("analysis_plan_fingerprint", ""),
                            "weighting": state.get("weighting_authority_fingerprint", "")}
        revision_fingerprint = canonical_digest(revision_payload, digest_provider=self.digest)
        revision = QuantitativeApprovedRevision(
            str(uuid5(NAMESPACE_URL, f"quant-approved-revision:{run_id}:{revision_fingerprint}")),
            project_id,
            run_id, "QUANTITATIVE/1", review.review_id, review.fingerprint,
            report.report_id, report.validation_fingerprint,
            state["dataset_record_id"], sources[0],
            state["analysis_manifest_record_id"], sources[1],
            state["finding_generation_record_id"], sources[2],
            state["insight_generation_record_id"], sources[3],
            revision_fingerprint,
            state.get("analysis_plan_fingerprint", ""),
            state.get("weighting_authority_fingerprint", ""),
        )
        self._persist_once(revision, revision.revision_id, project_id, run_id,
                           dataset.version_id, True)
        return review, revision

    def _persist_shared_review(self, review, *, state, report):
        if self.reviews is None:
            raise QuantitativeAnalysisError("shared Review repository is unavailable")
        existing = self.reviews.get_by_id(review.review_id)
        if existing is not None:
            if (existing.verdict != review.verdict
                    or existing.metadata.get("quant_review_fingerprint") != review.fingerprint):
                raise QuantitativeAnalysisError("conflicting shared Quant Review")
            return
        issues = tuple(ReviewIssue(
            id=f"{review.review_id}:issue:{index}",
            issue_type=ReviewIssueType.INCONSISTENT_ANALYSIS,
            severity=ReviewIssueSeverity.MAJOR,
            message=message,
        ) for index, message in enumerate(review.issues, 1))
        self.reviews.create(ReviewResult(
            id=review.review_id, project_id=review.project_id,
            workflow_run_id=review.run_id,
            research_design_id=str(uuid5(
                NAMESPACE_URL,
                f"quant-plan:{review.run_id}:{state.get('analysis_plan_version_id', '')}",
            )),
            report_id=report.report_id if report is not None else
                      state["report_composition_record_id"],
            review_attempt=1, verdict=review.verdict,
            quality_dimensions=(), issues=issues,
            summary="; ".join(review.issues) if review.issues else
                    "Quantitative package passed deterministic review",
            review_method="QNT04_DETERMINISTIC_REVIEW_V1",
            created_at=datetime.now(timezone.utc).isoformat(),
            deduplication_key=review.fingerprint,
            metadata={"methodology": "QUANTITATIVE",
                      "quant_review_fingerprint": review.fingerprint,
                      "dataset_record_id": review.dataset_record_id,
                      "analysis_plan_version_id": state.get("analysis_plan_version_id", ""),
                      "analysis_plan_fingerprint": review.analysis_plan_fingerprint,
                      "report_composition_record_id": review.report_composition_record_id},
        ))

    def _persist_once(self, value, record_id, project_id, run_id, dataset_version_id, accepted):
        if self.state._repository.get_for_project(record_id, project_id=project_id) is None:
            self.state.persist(value, record_id=record_id, project_id=project_id,
                               run_id=run_id, dataset_version_id=dataset_version_id,
                               accepted=accepted)
            return
        existing = self.state.load(record_id, project_id=project_id,
                                   expected_type=type(value))
        if existing != value:
            raise QuantitativeAnalysisError("conflicting immutable Quant Review record")

    def _validate(self, *, project_id, run_id, state, dataset, manifest,
                  findings, insights, composition):
        if (state.get("dataset_version_id"), state.get("dataset_fingerprint")) != (
                dataset.version_id, dataset.dataset_fingerprint):
            raise QuantitativeAnalysisError("reviewed dataset differs from pinned authority")
        if (state.get("analysis_execution_mode") not in (None, "DESIGN_AWARE_EXECUTION")
                or not state.get("analysis_plan_fingerprint")):
            raise QuantitativeAnalysisError("reviewed analysis plan is unavailable")
        if manifest.dataset_version_id != dataset.version_id or not manifest.statistical_result_record_ids:
            raise QuantitativeAnalysisError("analysis manifest is stale or empty")
        results = {}
        for record_id in manifest.statistical_result_record_ids:
            self.state.require_record_scope(record_id, project_id=project_id, run_id=run_id)
            result = self.state.load(record_id, project_id=project_id,
                                     expected_type=StatisticalResult)
            if (result.dataset_version_id, result.dataset_fingerprint,
                    result.data_fingerprint, result.codebook_fingerprint) != (
                    dataset.version_id, dataset.dataset_fingerprint,
                    dataset.data_fingerprint, dataset.codebook_fingerprint):
                raise QuantitativeAnalysisError("statistical result has foreign dataset authority")
            if result.result_id in results:
                raise QuantitativeAnalysisError("duplicate statistical result identity")
            results[result.result_id] = result
        comparisons = {}
        for record_id in manifest.comparison_record_ids:
            self.state.require_record_scope(record_id, project_id=project_id, run_id=run_id)
            item = self.state.load(record_id, project_id=project_id,
                                   expected_type=AnalyticalComparisonResult)
            if (item.dataset_version_id, item.dataset_fingerprint,
                    item.data_fingerprint) != (
                    dataset.version_id, dataset.dataset_fingerprint,
                    dataset.data_fingerprint):
                raise QuantitativeAnalysisError("comparison has foreign dataset authority")
            comparisons[item.comparison_result_id] = item
        if not findings.accepted_findings or not insights.accepted_insights:
            raise QuantitativeAnalysisError("review requires accepted Findings and Insights")
        finding_validator = CanonicalQuantFindingSupportValidator(
            digest_provider=self.digest, dataset=dataset, run_id=run_id)
        finding_map = {}
        for item in findings.accepted_findings:
            contexts = ({item.semantic_evidence_context.result_id:
                         item.semantic_evidence_context}
                        if item.semantic_evidence_context is not None else {})
            checked = finding_validator.validate(
                item, statistical_results=results, comparison_results=comparisons,
                semantic_evidence_contexts=contexts)
            if checked != item or item.finding_id in finding_map:
                raise QuantitativeAnalysisError("Finding is stale or no longer supported")
            finding_map[item.finding_id] = item
        insight_validator = CanonicalQuantInsightValidator(
            digest_provider=self.digest, require_canonical_authority=True)
        insight_map = {}
        for item in insights.accepted_insights:
            checked = insight_validator.validate(
                item, findings=finding_map,
                allow_interpretive_compatibility=True)
            if checked != item or item.insight_id in insight_map:
                raise QuantitativeAnalysisError("Insight is stale or no longer supported")
            insight_map[item.insight_id] = item
        report = composition.accepted_report
        if report is None or report.validation_status is not QuantitativeReportValidationStatus.SUPPORTED:
            raise QuantitativeAnalysisError("review requires a supported Report")
        validator = QuantitativeReportValidator(digest_provider=self.digest)
        checked = (validator.validate_derived_claim_units(report, findings=finding_map,
                                                          insights=insight_map)
                   if report.generation_version == "qk-3" else
                   validator.validate(report, findings=finding_map, insights=insight_map))
        if checked != report:
            raise QuantitativeAnalysisError("Report narrative or support changed after validation")
        limitation_ids = {item.insight_id for item in insight_map.values()
                          if item.insight_type.value == "LIMITATION"}
        if limitation_ids and (
                not any(section.section_type.value == "LIMITATIONS" for section in report.sections)
                or not limitation_ids.issubset(
                    {ref.authority_id for ref in report.supporting_insight_refs})):
            raise QuantitativeAnalysisError("Report omits accepted limitations")
        for section in report.sections:
            narrative = section.narrative.casefold()
            if re.search(r"\b(?:confidence interval|confidence bounds?|\d+%\s*ci)\b", narrative):
                raise QuantitativeAnalysisError("QNT V1 has no confidence interval authority")
            if re.search(r"\b(?:causes?|caused|causing|leads? to|led to|drives?|drove|resulted in)\b", narrative):
                raise QuantitativeAnalysisError("causal Report narrative is unsupported")
            support = tuple(finding_map[ref.authority_id] for ref in section.finding_refs)
            supported_weights = {item.claim.weighting_status for item in support}
            if re.search(r"\bunweighted\b", narrative) and supported_weights != {"UNWEIGHTED"}:
                raise QuantitativeAnalysisError("Report weighting statement contradicts Findings")
            if re.search(r"\bweighted\b", narrative) and supported_weights != {"WEIGHTED"}:
                raise QuantitativeAnalysisError("Report weighting statement contradicts Findings")
