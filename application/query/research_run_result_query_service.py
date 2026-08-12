"""Compose a coherent ResearchRunResult from canonical persisted state."""

from __future__ import annotations

from typing import Any

from application.persistence.exceptions import EntityNotFoundError
from application.persistence.records import ArtifactRecord
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportRepository
from application.ports.review_ports import ReviewRepository
from application.ports.source_ports import SourceRepository
from application.ports.workflow_run_repository import WorkflowRunRepository
from application.query.research_run_result import (
    ArtifactStatusProjection,
    BoundedTextProjection,
    BudgetUsageProjection,
    CollectionSummary,
    DETAIL_TEXT_BOUND,
    DetailTruncationProjection,
    EntityRefItem,
    EVIDENCE_EXCERPT_DETAIL_BOUND,
    EvidenceDetailItem,
    EXECUTIVE_SUMMARY_DETAIL_BOUND,
    FindingDetailItem,
    InsightDetailItem,
    MAX_DETAIL_COLLECTION_ITEMS,
    ProvenanceLink,
    ProvenanceSummary,
    QualityDimensionDetailItem,
    ReadinessProjection,
    REPORT_SECTION_CONTENT_BOUND,
    REPORT_TOTAL_CONTENT_BOUND,
    ReportDetailProjection,
    ReportProjection,
    ReportSectionDetailItem,
    ResearchRunDetailPayload,
    ResearchRunOutcome,
    ResearchRunResult,
    ResearchRunResultDetail,
    ResearchRunResultProjectionError,
    ReviewDetailProjection,
    ReviewIssueDetailItem,
    REVIEW_DETAIL_SUMMARY_BOUND,
    REVIEW_ISSUE_MESSAGE_BOUND,
    ReviewProjection,
    SourceDetailItem,
)
from application.research_quality.readiness_result_codec import (
    extract_research_readiness,
)
from application.research_quality.workflow_task_ids import (
    DOWNSTREAM_TASK_DEFINITION_IDS,
    TASK_ASSESS_RESEARCH_READINESS,
)
from application.sources.provenance_merge import is_successful_acquisition
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reviews.review_issue import ReviewIssueSeverity
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.task_status import TaskStatus
from domain.workflow_run import WorkflowRun
from domain.workflow_status import WorkflowStatus

STATEMENT_BOUND = 280
EXECUTIVE_SUMMARY_BOUND = 500
REVIEW_SUMMARY_BOUND = 280
RUN_USAGE_SUMMARY_KEY = "_run_usage_summary"


class ResearchRunResultQueryService:
    """Read-only projection of a terminal Research run into ResearchRunResult."""

    def __init__(
        self,
        *,
        workflow_run_repository: WorkflowRunRepository,
        source_repository: SourceRepository,
        evidence_repository: EvidenceRepository,
        finding_repository: FindingRepository,
        insight_repository: InsightRepository,
        report_repository: ReportRepository,
        review_repository: ReviewRepository,
        artifact_repository: ArtifactRepository,
    ) -> None:
        self._workflow_run_repository = workflow_run_repository
        self._source_repository = source_repository
        self._evidence_repository = evidence_repository
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._report_repository = report_repository
        self._review_repository = review_repository
        self._artifact_repository = artifact_repository

    def get_for_run(self, run_id: str) -> ResearchRunResult:
        workflow_run = self._workflow_run_repository.get_by_id(run_id)
        if workflow_run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        if not workflow_run.is_terminal:
            raise ResearchRunResultProjectionError(
                f"WorkflowRun is not terminal: {run_id}",
            )

        task_results = self._workflow_run_repository.get_task_results(run_id)
        project_id = workflow_run.project_id

        sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        evidence = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        findings = self._finding_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        insights = self._insight_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        reports = self._report_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        reviews = self._review_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        artifacts = self._artifact_repository.list_for_run(run_id)

        readiness_payload = extract_research_readiness(task_results)
        readiness = self._project_readiness(readiness_payload)
        latest_report = self._select_latest_report(reports)
        latest_review = self._select_latest_review(reviews, latest_report)
        approved_artifact = self._select_approved_artifact(artifacts, reports)
        artifact_status = self._project_artifact_status(
            artifacts,
            approved_artifact,
        )

        outcome = self._derive_outcome(
            workflow_run=workflow_run,
            readiness_payload=readiness_payload,
            reviews=reviews,
            latest_review=latest_review,
            approved_artifact=approved_artifact,
            artifacts=artifacts,
        )

        limitations = self._project_limitations(
            readiness_payload=readiness_payload,
            latest_report=latest_report,
        )
        termination_reason = readiness.termination_reason
        budget_usage = self._project_budget_usage(task_results)
        provenance = self._project_provenance(
            run_id=run_id,
            latest_report=latest_report,
            findings=findings,
            insights=insights,
            evidence=evidence,
            sources=sources,
        )

        return ResearchRunResult(
            run_id=run_id,
            project_id=project_id,
            workflow_status=workflow_run.status.value,
            outcome=outcome,
            readiness=readiness,
            termination_reason=termination_reason,
            limitations=limitations,
            budget_usage=budget_usage,
            source_summary=self._project_sources(sources),
            evidence_summary=self._project_evidence(evidence),
            finding_summary=self._project_findings(findings),
            insight_summary=self._project_insights(insights),
            latest_report=(
                self._project_report(latest_report)
                if latest_report is not None
                else None
            ),
            latest_review=(
                self._project_review(latest_review)
                if latest_review is not None
                else None
            ),
            artifact_status=artifact_status,
            provenance_summary=provenance,
            correlation_id=self._correlation_id(workflow_run, task_results),
        )

    def get_detail_for_run(self, run_id: str) -> ResearchRunResultDetail:
        """Project terminal Research run into summary + bounded inspectable detail."""
        result = self.get_for_run(run_id)
        workflow_run = self._workflow_run_repository.get_by_id(run_id)
        if workflow_run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")

        project_id = workflow_run.project_id
        sources = self._source_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        evidence = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        findings = self._finding_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        insights = self._insight_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        reports = self._report_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )
        reviews = self._review_repository.list_for_project(
            project_id,
            workflow_run_id=run_id,
        )

        latest_report_entity = self._select_latest_report(reports)
        latest_review_entity = self._select_latest_review(
            reviews,
            latest_report_entity,
        )

        detail = self._project_detail_payload(
            run_id=run_id,
            sources=sources,
            evidence=evidence,
            findings=findings,
            insights=insights,
            latest_report=latest_report_entity,
            latest_review=latest_review_entity,
            summary_report=result.latest_report,
            summary_review=result.latest_review,
        )

        return ResearchRunResultDetail(result=result, detail=detail)

    def _derive_outcome(
        self,
        *,
        workflow_run: WorkflowRun,
        readiness_payload: dict[str, Any] | None,
        reviews: list[ReviewResult],
        latest_review: ReviewResult | None,
        approved_artifact: ArtifactRecord | None,
        artifacts: list[ArtifactRecord],
    ) -> ResearchRunOutcome:
        if approved_artifact is not None:
            supporting = self._supporting_approve_review(
                reviews,
                approved_artifact,
            )
            if supporting is None:
                raise ResearchRunResultProjectionError(
                    "Approved artifact exists without supporting approve review",
                )
            if latest_review is not None and latest_review.verdict != ReviewVerdict.APPROVE:
                # Stale non-approve reviews may exist for earlier revisions; approve
                # for the approved report_id is authoritative.
                if supporting.report_id != approved_artifact.report_id:
                    raise ResearchRunResultProjectionError(
                        "Approved artifact contradicts non-approve review linkage",
                    )
            return ResearchRunOutcome.APPROVED

        if self._is_quality_rejected(
            workflow_run=workflow_run,
            reviews=reviews,
            latest_review=latest_review,
            artifacts=artifacts,
        ):
            return ResearchRunOutcome.QUALITY_REJECTED

        if self._is_not_ready(
            workflow_run=workflow_run,
            readiness_payload=readiness_payload,
        ):
            return ResearchRunOutcome.NOT_READY

        if workflow_run.status in {WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}:
            return ResearchRunOutcome.EXECUTION_FAILED

        raise ResearchRunResultProjectionError(
            "Ambiguous terminal Research state; refusing to fabricate outcome",
        )

    def _supporting_approve_review(
        self,
        reviews: list[ReviewResult],
        approved_artifact: ArtifactRecord,
    ) -> ReviewResult | None:
        candidates = [
            review
            for review in reviews
            if review.verdict == ReviewVerdict.APPROVE
            and (
                approved_artifact.report_id is None
                or review.report_id == approved_artifact.report_id
            )
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.review_attempt, item.created_at, item.id),
        )

    def _is_quality_rejected(
        self,
        *,
        workflow_run: WorkflowRun,
        reviews: list[ReviewResult],
        latest_review: ReviewResult | None,
        artifacts: list[ArtifactRecord],
    ) -> bool:
        if latest_review is None or not reviews:
            return False
        verdict = latest_review.verdict
        if verdict == ReviewVerdict.APPROVE:
            raise ResearchRunResultProjectionError(
                "Approve review without approved artifact",
            )
        if verdict == ReviewVerdict.REJECT:
            return True
        if verdict != ReviewVerdict.REVISE:
            raise ResearchRunResultProjectionError(
                f"Unsupported review verdict for projection: {verdict}",
            )
        rejected_present = any(
            str(item.status).lower() == "rejected" for item in artifacts
        )
        review_task = self._task_by_definition(workflow_run, "task-review-report")
        review_failed = (
            review_task is not None and review_task.status == TaskStatus.FAILED
        )
        return (
            workflow_run.status == WorkflowStatus.FAILED
            or rejected_present
            or review_failed
        )

    def _is_not_ready(
        self,
        *,
        workflow_run: WorkflowRun,
        readiness_payload: dict[str, Any] | None,
    ) -> bool:
        readiness_task = self._task_by_definition(
            workflow_run,
            TASK_ASSESS_RESEARCH_READINESS,
        )
        if readiness_task is None or readiness_task.status != TaskStatus.COMPLETED:
            return False
        if readiness_payload is None:
            return False

        ready = readiness_payload.get("ready_for_analysis")
        research_outcome = readiness_payload.get("research_outcome")
        insufficient = ready is False or research_outcome == "insufficient_research"
        if not insufficient:
            return False
        if workflow_run.status != WorkflowStatus.COMPLETED:
            return False

        # Legitimate research stop before Analysis: downstream stages skipped.
        for definition_id in DOWNSTREAM_TASK_DEFINITION_IDS:
            task = self._task_by_definition(workflow_run, definition_id)
            if task is None:
                continue
            if task.status not in {TaskStatus.SKIPPED, TaskStatus.CANCELLED}:
                # Downstream may be absent on older templates; if present and not
                # skipped, this is not a clean NOT_READY projection.
                return False
        return True

    @staticmethod
    def _task_by_definition(workflow_run: WorkflowRun, definition_id: str):
        for task in workflow_run.tasks:
            if task.definition_id == definition_id:
                return task
        return None

    @staticmethod
    def _select_latest_report(reports: list[Report]) -> Report | None:
        if not reports:
            return None
        return max(reports, key=lambda item: (item.revision_number, item.id))

    @staticmethod
    def _select_latest_review(
        reviews: list[ReviewResult],
        latest_report: Report | None,
    ) -> ReviewResult | None:
        if not reviews:
            return None
        scoped = reviews
        if latest_report is not None:
            matched = [item for item in reviews if item.report_id == latest_report.id]
            if matched:
                scoped = matched
        return max(
            scoped,
            key=lambda item: (item.review_attempt, item.created_at, item.id),
        )

    @staticmethod
    def _select_approved_artifact(
        artifacts: list[ArtifactRecord],
        reports: list[Report],
    ) -> ArtifactRecord | None:
        approved = [
            item for item in artifacts if str(item.status).lower() == "approved"
        ]
        if not approved:
            return None
        report_revision = {
            report.id: report.revision_number for report in reports
        }

        def _key(item: ArtifactRecord) -> tuple[int, str]:
            revision = report_revision.get(item.report_id or "", -1)
            return (revision, item.id)

        return max(approved, key=_key)

    @staticmethod
    def _project_readiness(
        payload: dict[str, Any] | None,
    ) -> ReadinessProjection:
        if payload is None:
            return ReadinessProjection(
                ready_for_analysis=None,
                research_outcome=None,
                termination_reason=None,
                blocking_information_need_ids=(),
                blocking_research_question_ids=(),
                targeted_research_required=None,
                available=False,
            )
        blocking_needs = tuple(
            sorted(
                str(item)
                for item in payload.get("blocking_information_need_ids", []) or []
            ),
        )
        blocking_rqs = tuple(
            sorted(
                str(item)
                for item in payload.get("blocking_research_question_ids", []) or []
            ),
        )
        ready = payload.get("ready_for_analysis")
        targeted = payload.get("targeted_research_required")
        return ReadinessProjection(
            ready_for_analysis=bool(ready) if ready is not None else None,
            research_outcome=(
                str(payload["research_outcome"])
                if payload.get("research_outcome") is not None
                else None
            ),
            termination_reason=(
                str(payload.get("termination_reason") or "") or None
            ),
            blocking_information_need_ids=blocking_needs,
            blocking_research_question_ids=blocking_rqs,
            targeted_research_required=(
                bool(targeted) if targeted is not None else None
            ),
            available=True,
        )

    @staticmethod
    def _project_limitations(
        *,
        readiness_payload: dict[str, Any] | None,
        latest_report: Report | None,
    ) -> tuple[str, ...]:
        limitations: list[str] = []
        if latest_report is not None:
            limitations.extend(str(item) for item in latest_report.limitations)
        if readiness_payload is not None:
            reason = str(readiness_payload.get("termination_reason") or "").strip()
            if reason and reason not in limitations:
                limitations.append(reason)
            outcome = str(readiness_payload.get("research_outcome") or "").strip()
            if outcome == "insufficient_research" and outcome not in limitations:
                limitations.append(outcome)
        return tuple(limitations)

    @staticmethod
    def _project_budget_usage(task_results: dict[str, Any]) -> BudgetUsageProjection:
        raw = task_results.get(RUN_USAGE_SUMMARY_KEY)
        if not isinstance(raw, dict) or not raw:
            return BudgetUsageProjection(available=False, partial=True, stages={})
        stages = raw.get("stages")
        stage_payload = dict(stages) if isinstance(stages, dict) else {}
        has_core = any(
            key in raw
            for key in (
                "total_llm_calls",
                "estimated_cost_usd",
                "budget_exhausted",
                "stages",
            )
        )
        return BudgetUsageProjection(
            available=has_core,
            partial=not has_core,
            total_llm_calls=(
                int(raw["total_llm_calls"])
                if raw.get("total_llm_calls") is not None
                else None
            ),
            estimated_cost_usd=(
                float(raw["estimated_cost_usd"])
                if raw.get("estimated_cost_usd") is not None
                else None
            ),
            budget_exhausted=(
                bool(raw["budget_exhausted"])
                if raw.get("budget_exhausted") is not None
                else None
            ),
            exhaustion_stage=(
                str(raw["exhaustion_stage"])
                if raw.get("exhaustion_stage") is not None
                else None
            ),
            exhaustion_reason=(
                str(raw["exhaustion_reason"])
                if raw.get("exhaustion_reason") is not None
                else None
            ),
            stages=stage_payload,
        )

    @staticmethod
    def _bound_text(value: str, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)] + "…"

    def _project_sources(self, sources: list[Source]) -> CollectionSummary:
        ordered = sorted(sources, key=lambda item: item.id)
        acquired = sum(
            1
            for item in ordered
            if is_successful_acquisition(item.retrieval_status)
        )
        failed = sum(
            1 for item in ordered if item.retrieval_status == RetrievalStatus.FAILED
        )
        truncated = sum(
            1
            for item in ordered
            if item.retrieval_status == RetrievalStatus.TRUNCATED
        )
        items = tuple(
            EntityRefItem(id=item.id, statement=None, source_id=None)
            for item in ordered
        )
        return CollectionSummary(
            count=len(ordered),
            ids=tuple(item.id for item in ordered),
            items=items,
            acquired_count=acquired,
            failed_count=failed,
            truncated_count=truncated,
        )

    def _project_evidence(self, evidence: list[Evidence]) -> CollectionSummary:
        ordered = sorted(evidence, key=lambda item: item.id)
        items = tuple(
            EntityRefItem(
                id=item.id,
                statement=self._bound_text(item.statement, STATEMENT_BOUND),
                source_id=item.source_id,
            )
            for item in ordered
        )
        return CollectionSummary(
            count=len(ordered),
            ids=tuple(item.id for item in ordered),
            items=items,
        )

    def _project_findings(self, findings: list[Finding]) -> CollectionSummary:
        ordered = sorted(findings, key=lambda item: item.id)
        items = tuple(
            EntityRefItem(
                id=item.id,
                statement=self._bound_text(item.statement, STATEMENT_BOUND),
            )
            for item in ordered
        )
        return CollectionSummary(
            count=len(ordered),
            ids=tuple(item.id for item in ordered),
            items=items,
        )

    def _project_insights(self, insights: list[Insight]) -> CollectionSummary:
        ordered = sorted(insights, key=lambda item: item.id)
        items = tuple(
            EntityRefItem(
                id=item.id,
                statement=self._bound_text(item.statement, STATEMENT_BOUND),
            )
            for item in ordered
        )
        return CollectionSummary(
            count=len(ordered),
            ids=tuple(item.id for item in ordered),
            items=items,
        )

    def _project_report(self, report: Report) -> ReportProjection:
        return ReportProjection(
            id=report.id,
            revision_number=report.revision_number,
            previous_report_id=report.previous_report_id,
            title=report.title,
            section_count=len(report.sections),
            finding_ref_count=len(report.finding_refs),
            insight_ref_count=len(report.insight_refs),
            evidence_ref_count=len(report.evidence_refs),
            limitations=tuple(str(item) for item in report.limitations),
            executive_summary=self._bound_text(
                report.executive_summary,
                EXECUTIVE_SUMMARY_BOUND,
            ),
        )

    def _project_review(self, review: ReviewResult) -> ReviewProjection:
        major = sum(
            1
            for issue in review.issues
            if issue.severity == ReviewIssueSeverity.MAJOR
        )
        minor = sum(
            1
            for issue in review.issues
            if issue.severity == ReviewIssueSeverity.MINOR
        )
        return ReviewProjection(
            id=review.id,
            report_id=review.report_id,
            review_attempt=review.review_attempt,
            verdict=review.verdict.value,
            issue_count=len(review.issues),
            major_issue_count=major,
            minor_issue_count=minor,
            summary=self._bound_text(review.summary, REVIEW_SUMMARY_BOUND),
            artifact_id=review.artifact_id,
        )

    @staticmethod
    def _project_artifact_status(
        artifacts: list[ArtifactRecord],
        approved_artifact: ArtifactRecord | None,
    ) -> ArtifactStatusProjection:
        ordered = sorted(artifacts, key=lambda item: item.id)
        statuses = tuple(
            {
                "id": item.id,
                "status": str(item.status).lower(),
                "report_id": item.report_id,
            }
            for item in ordered
        )
        approved_count = sum(1 for item in ordered if str(item.status).lower() == "approved")
        rejected_count = sum(1 for item in ordered if str(item.status).lower() == "rejected")
        draft_count = sum(1 for item in ordered if str(item.status).lower() == "draft")
        return ArtifactStatusProjection(
            count=len(ordered),
            approved_count=approved_count,
            rejected_count=rejected_count,
            draft_count=draft_count,
            approved_artifact_id=(
                approved_artifact.id if approved_artifact is not None else None
            ),
            approved_report_id=(
                approved_artifact.report_id if approved_artifact is not None else None
            ),
            statuses=statuses,
        )

    def _project_provenance(
        self,
        *,
        run_id: str,
        latest_report: Report | None,
        findings: list[Finding],
        insights: list[Insight],
        evidence: list[Evidence],
        sources: list[Source],
    ) -> ProvenanceSummary:
        finding_by_id = {
            item.id: item for item in findings if item.workflow_run_id == run_id
        }
        insight_by_id = {
            item.id: item for item in insights if item.workflow_run_id == run_id
        }
        evidence_by_id = {
            item.id: item for item in evidence if item.workflow_run_id == run_id
        }
        source_by_id = {
            item.id: item
            for item in sources
            if run_id in item.workflow_run_refs
        }

        unresolved: list[dict[str, str]] = []
        links: list[ProvenanceLink] = []
        finding_ids: set[str] = set()
        insight_ids: set[str] = set()
        evidence_ids: set[str] = set()
        source_ids: set[str] = set()

        if latest_report is None:
            return ProvenanceSummary(
                report_id=None,
                finding_ids=(),
                insight_ids=(),
                evidence_ids=(),
                source_ids=(),
                links=(),
                unresolved_refs=(),
            )

        def _mark_unresolved(kind: str, ref_id: str) -> None:
            unresolved.append({"kind": kind, "id": ref_id})

        for finding_id in latest_report.finding_refs:
            finding = finding_by_id.get(finding_id)
            if finding is None:
                _mark_unresolved("finding", finding_id)
                continue
            finding_ids.add(finding.id)
            for evidence_id in finding.evidence_refs:
                evidence_item = evidence_by_id.get(evidence_id)
                if evidence_item is None:
                    _mark_unresolved("evidence", evidence_id)
                    continue
                evidence_ids.add(evidence_item.id)
                source = source_by_id.get(evidence_item.source_id)
                if source is None:
                    _mark_unresolved("source", evidence_item.source_id)
                    continue
                source_ids.add(source.id)
                links.append(
                    ProvenanceLink(
                        finding_id=finding.id,
                        insight_id=None,
                        evidence_id=evidence_item.id,
                        source_id=source.id,
                    ),
                )

        for insight_id in latest_report.insight_refs:
            insight = insight_by_id.get(insight_id)
            if insight is None:
                _mark_unresolved("insight", insight_id)
                continue
            insight_ids.add(insight.id)
            for finding_id in insight.finding_refs:
                finding = finding_by_id.get(finding_id)
                if finding is None:
                    _mark_unresolved("finding", finding_id)
                    continue
                finding_ids.add(finding.id)
                for evidence_id in finding.evidence_refs:
                    evidence_item = evidence_by_id.get(evidence_id)
                    if evidence_item is None:
                        _mark_unresolved("evidence", evidence_id)
                        continue
                    evidence_ids.add(evidence_item.id)
                    source = source_by_id.get(evidence_item.source_id)
                    if source is None:
                        _mark_unresolved("source", evidence_item.source_id)
                        continue
                    source_ids.add(source.id)
                    links.append(
                        ProvenanceLink(
                            finding_id=finding.id,
                            insight_id=insight.id,
                            evidence_id=evidence_item.id,
                            source_id=source.id,
                        ),
                    )

        for evidence_id in latest_report.evidence_refs:
            evidence_item = evidence_by_id.get(evidence_id)
            if evidence_item is None:
                _mark_unresolved("evidence", evidence_id)
                continue
            evidence_ids.add(evidence_item.id)
            source = source_by_id.get(evidence_item.source_id)
            if source is None:
                _mark_unresolved("source", evidence_item.source_id)
                continue
            source_ids.add(source.id)
            links.append(
                ProvenanceLink(
                    finding_id=None,
                    insight_id=None,
                    evidence_id=evidence_item.id,
                    source_id=source.id,
                ),
            )

        # Citation registry source_ids (canonical, non-heuristic).
        for citation in latest_report.citation_registry.values():
            if not isinstance(citation, dict):
                continue
            source_id = citation.get("source_id")
            if source_id is None:
                continue
            source_id = str(source_id)
            source = source_by_id.get(source_id)
            if source is None:
                _mark_unresolved("source", source_id)
                continue
            source_ids.add(source.id)

        # Deterministic ordering for stable projections.
        unique_links: list[ProvenanceLink] = []
        seen_link_keys: set[tuple[str | None, str | None, str, str]] = set()
        for link in sorted(
            links,
            key=lambda item: (
                item.finding_id or "",
                item.insight_id or "",
                item.evidence_id,
                item.source_id,
            ),
        ):
            key = (
                link.finding_id,
                link.insight_id,
                link.evidence_id,
                link.source_id,
            )
            if key in seen_link_keys:
                continue
            seen_link_keys.add(key)
            unique_links.append(link)

        unresolved_sorted = tuple(
            sorted(unresolved, key=lambda item: (item["kind"], item["id"])),
        )
        return ProvenanceSummary(
            report_id=latest_report.id,
            finding_ids=tuple(sorted(finding_ids)),
            insight_ids=tuple(sorted(insight_ids)),
            evidence_ids=tuple(sorted(evidence_ids)),
            source_ids=tuple(sorted(source_ids)),
            links=tuple(unique_links),
            unresolved_refs=unresolved_sorted,
        )

    @staticmethod
    def _correlation_id(
        workflow_run: WorkflowRun,
        task_results: dict[str, Any],
    ) -> str | None:
        # Prefer explicit metadata if present on the run via task results root.
        for snapshot in task_results.values():
            if not isinstance(snapshot, dict):
                continue
            shared = snapshot.get("shared_state")
            if isinstance(shared, dict) and shared.get("correlation_id"):
                return str(shared["correlation_id"])
        return None

    @staticmethod
    def _bound_detail_text(value: str, limit: int) -> BoundedTextProjection:
        text = str(value or "")
        original_length = len(text)
        if original_length <= limit:
            return BoundedTextProjection(
                value=text,
                truncated=False,
                original_length=original_length,
            )
        return BoundedTextProjection(
            value=text[: max(0, limit - 1)] + "…",
            truncated=True,
            original_length=original_length,
        )

    @staticmethod
    def _run_scoped_sources(sources: list[Source], run_id: str) -> list[Source]:
        return sorted(
            [
                item
                for item in sources
                if run_id in item.workflow_run_refs
            ],
            key=lambda item: item.id,
        )

    @staticmethod
    def _run_scoped_evidence(evidence: list[Evidence], run_id: str) -> list[Evidence]:
        return sorted(
            [item for item in evidence if item.workflow_run_id == run_id],
            key=lambda item: item.id,
        )

    @staticmethod
    def _run_scoped_findings(findings: list[Finding], run_id: str) -> list[Finding]:
        return sorted(
            [item for item in findings if item.workflow_run_id == run_id],
            key=lambda item: item.id,
        )

    @staticmethod
    def _run_scoped_insights(insights: list[Insight], run_id: str) -> list[Insight]:
        return sorted(
            [item for item in insights if item.workflow_run_id == run_id],
            key=lambda item: item.id,
        )

    @staticmethod
    def _truncate_collection(
        items: list[Any],
        *,
        max_items: int,
    ) -> tuple[list[Any], bool]:
        if len(items) <= max_items:
            return items, False
        return items[:max_items], True

    def _project_detail_payload(
        self,
        *,
        run_id: str,
        sources: list[Source],
        evidence: list[Evidence],
        findings: list[Finding],
        insights: list[Insight],
        latest_report: Report | None,
        latest_review: ReviewResult | None,
        summary_report: ReportProjection | None,
        summary_review: ReviewProjection | None,
    ) -> ResearchRunDetailPayload:
        scoped_sources = self._run_scoped_sources(sources, run_id)
        scoped_evidence = self._run_scoped_evidence(evidence, run_id)
        scoped_findings = self._run_scoped_findings(findings, run_id)
        scoped_insights = self._run_scoped_insights(insights, run_id)

        evidence_count_by_source: dict[str, int] = {}
        for item in scoped_evidence:
            evidence_count_by_source[item.source_id] = (
                evidence_count_by_source.get(item.source_id, 0) + 1
            )

        total_counts = {
            "sources": len(scoped_sources),
            "evidence": len(scoped_evidence),
            "findings": len(scoped_findings),
            "insights": len(scoped_insights),
        }

        sources_slice, sources_truncated = self._truncate_collection(
            scoped_sources,
            max_items=MAX_DETAIL_COLLECTION_ITEMS,
        )
        evidence_slice, evidence_truncated = self._truncate_collection(
            scoped_evidence,
            max_items=MAX_DETAIL_COLLECTION_ITEMS,
        )
        findings_slice, findings_truncated = self._truncate_collection(
            scoped_findings,
            max_items=MAX_DETAIL_COLLECTION_ITEMS,
        )
        insights_slice, insights_truncated = self._truncate_collection(
            scoped_insights,
            max_items=MAX_DETAIL_COLLECTION_ITEMS,
        )

        source_details = tuple(
            SourceDetailItem(
                id=item.id,
                title=item.title,
                publisher=item.publisher,
                url=item.url,
                canonical_url=item.canonical_url,
                source_type=item.source_type,
                content_type=item.content_type,
                retrieval_status=item.retrieval_status.value,
                truncated=item.retrieval_status == RetrievalStatus.TRUNCATED,
                evidence_count=evidence_count_by_source.get(item.id, 0),
                language=item.language,
                published_at=item.published_at,
                retrieved_at=item.retrieved_at,
            )
            for item in sources_slice
        )

        evidence_details = tuple(
            EvidenceDetailItem(
                id=item.id,
                statement=self._bound_detail_text(item.statement, DETAIL_TEXT_BOUND),
                source_excerpt=self._bound_detail_text(
                    item.source_excerpt,
                    EVIDENCE_EXCERPT_DETAIL_BOUND,
                ),
                source_id=item.source_id,
                evidence_type=item.evidence_type.value,
                research_question_refs=item.research_question_refs,
                information_need_refs=item.information_need_refs,
                confidence=item.confidence,
                source_locator=dict(item.source_locator) if item.source_locator else {},
            )
            for item in evidence_slice
        )

        finding_details = tuple(
            FindingDetailItem(
                id=item.id,
                statement=self._bound_detail_text(item.statement, DETAIL_TEXT_BOUND),
                rationale=self._bound_detail_text(item.rationale, DETAIL_TEXT_BOUND),
                evidence_refs=item.evidence_refs,
                research_question_refs=item.research_question_refs,
                information_need_refs=item.information_need_refs,
                confidence=item.confidence,
            )
            for item in findings_slice
        )

        insight_details = tuple(
            InsightDetailItem(
                id=item.id,
                statement=self._bound_detail_text(item.statement, DETAIL_TEXT_BOUND),
                implication=self._bound_detail_text(item.implication, DETAIL_TEXT_BOUND),
                finding_refs=item.finding_refs,
                research_question_refs=item.research_question_refs,
                confidence=item.confidence,
            )
            for item in insights_slice
        )

        report_detail: ReportDetailProjection | None = None
        report_truncated = False
        section_truncated_ids: list[str] = []
        if summary_report is not None and latest_report is not None:
            report_detail, report_truncated, section_truncated_ids = (
                self._project_report_detail(latest_report)
            )

        review_detail: ReviewDetailProjection | None = None
        if summary_review is not None and latest_review is not None:
            review_detail = self._project_review_detail(latest_review)

        collection_truncated = any(
            (
                sources_truncated,
                evidence_truncated,
                findings_truncated,
                insights_truncated,
            ),
        )

        truncation = DetailTruncationProjection(
            collection_truncated=collection_truncated,
            total_counts=total_counts,
            report_truncated=report_truncated,
            section_truncated_ids=tuple(sorted(section_truncated_ids)),
        )

        return ResearchRunDetailPayload(
            sources=source_details,
            evidence=evidence_details,
            findings=finding_details,
            insights=insight_details,
            report=report_detail,
            review=review_detail,
            truncation=truncation,
        )

    def _project_report_detail(
        self,
        report: Report,
    ) -> tuple[ReportDetailProjection, bool, list[str]]:
        section_truncated_ids: list[str] = []
        report_truncated = False
        total_content_chars = 0
        section_details: list[ReportSectionDetailItem] = []

        for section in report.sections:
            remaining_budget = REPORT_TOTAL_CONTENT_BOUND - total_content_chars
            if remaining_budget <= 0:
                report_truncated = True
                bounded = BoundedTextProjection(value="", truncated=True, original_length=len(section.content))
                section_truncated_ids.append(section.id)
            else:
                per_section_limit = min(REPORT_SECTION_CONTENT_BOUND, remaining_budget)
                bounded = self._bound_detail_text(section.content, per_section_limit)
                if bounded.truncated:
                    section_truncated_ids.append(section.id)
            total_content_chars += len(bounded.value)
            if bounded.truncated or total_content_chars >= REPORT_TOTAL_CONTENT_BOUND:
                report_truncated = True

            section_details.append(
                ReportSectionDetailItem(
                    id=section.id,
                    title=section.title,
                    content=bounded,
                    finding_refs=section.finding_refs,
                    insight_refs=section.insight_refs,
                    evidence_refs=section.evidence_refs,
                    citation_ids=section.citation_ids,
                ),
            )

        return (
            ReportDetailProjection(
                id=report.id,
                title=report.title,
                executive_summary=self._bound_detail_text(
                    report.executive_summary,
                    EXECUTIVE_SUMMARY_DETAIL_BOUND,
                ),
                limitations=tuple(str(item) for item in report.limitations),
                revision_number=report.revision_number,
                previous_report_id=report.previous_report_id,
                sections=tuple(section_details),
                citation_registry=self._project_citation_registry(
                    report.citation_registry,
                ),
            ),
            report_truncated,
            section_truncated_ids,
        )

    @staticmethod
    def _project_citation_registry(
        registry: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        safe: dict[str, dict[str, Any]] = {}
        for key in sorted(registry):
            value = registry[key]
            if not isinstance(value, dict):
                continue
            entry: dict[str, Any] = {
                "citation_id": str(value.get("citation_id", key)),
            }
            source_id = value.get("source_id")
            if source_id is not None:
                entry["source_id"] = str(source_id)
            label = value.get("label")
            if label:
                entry["label"] = str(label)[:200]
            safe[str(key)] = entry
        return safe

    def _project_review_detail(self, review: ReviewResult) -> ReviewDetailProjection:
        issues = tuple(
            ReviewIssueDetailItem(
                id=issue.id,
                issue_type=issue.issue_type.value,
                severity=issue.severity.value,
                message=self._bound_detail_text(
                    issue.message,
                    REVIEW_ISSUE_MESSAGE_BOUND,
                ),
                report_section_id=issue.report_section_id,
                finding_refs=issue.finding_refs,
                insight_refs=issue.insight_refs,
                evidence_refs=issue.evidence_refs,
                source_refs=issue.source_refs,
                research_question_refs=issue.research_question_refs,
                suggested_action=issue.suggested_action,
            )
            for issue in review.issues
        )
        quality_dimensions = tuple(
            QualityDimensionDetailItem(
                name=dimension.name.value,
                status=dimension.status.value,
                message=self._bound_detail_text(dimension.message, DETAIL_TEXT_BOUND),
            )
            for dimension in review.quality_dimensions
        )
        return ReviewDetailProjection(
            id=review.id,
            report_id=review.report_id,
            artifact_id=review.artifact_id,
            verdict=review.verdict.value,
            review_attempt=review.review_attempt,
            previous_report_id=review.previous_report_id,
            summary=self._bound_detail_text(
                review.summary,
                REVIEW_DETAIL_SUMMARY_BOUND,
            ),
            issues=issues,
            quality_dimensions=quality_dimensions,
        )
