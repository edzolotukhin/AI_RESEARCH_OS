from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.planning.research_design import ResearchDesign
from domain.reviews.review_result import ReviewResult

from application.persistence.records import ArtifactRecord
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportEngine, ReportInput, ReportRepository, ReportSectionCandidate
from application.ports.source_ports import SourceRepository
from application.report.citation_registry import CitationRegistry
from application.report.content_batching import (
    batch_findings_by_question,
    insights_for_question,
    resolve_section_titles,
)
from application.report.deduplication import (
    DR06_RESEARCH_REPORT_TYPE,
    compute_artifact_deduplication_key,
    compute_content_checksum,
    compute_report_deduplication_key,
)
from application.report.exceptions import (
    DuplicateArtifactError,
    DuplicateReportError,
    InvalidReportProvenanceError,
    ReportError,
)
from application.report.markdown_renderer import render_report_markdown, safe_report_filename
from application.report.provenance_validation import (
    collect_evidence_refs_for_section,
    validate_section_candidate,
)

from runtime.workflow_context import WorkflowContext

_MAX_DEDUP_RETRIES = 5


@dataclass(frozen=True)
class ReportSummary:
    report_id: str
    artifact_id: str
    section_count: int
    sections_rejected: int
    batch_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "artifact_id": self.artifact_id,
            "section_count": self.section_count,
            "sections_rejected": self.sections_rejected,
            "batch_failures": self.batch_failures,
        }


class ReportService:
    """Transform run-scoped Findings/Insights into a Report and Markdown Artifact."""

    def __init__(
        self,
        *,
        report_engine: ReportEngine,
        finding_repository: FindingRepository,
        insight_repository: InsightRepository,
        evidence_repository: EvidenceRepository,
        source_repository: SourceRepository,
        report_repository: ReportRepository,
        artifact_repository: ArtifactRepository,
        max_findings_per_batch: int,
        max_chars_per_batch: int,
    ) -> None:
        self._report_engine = report_engine
        self._finding_repository = finding_repository
        self._insight_repository = insight_repository
        self._evidence_repository = evidence_repository
        self._source_repository = source_repository
        self._report_repository = report_repository
        self._artifact_repository = artifact_repository
        self._max_findings_per_batch = max_findings_per_batch
        self._max_chars_per_batch = max_chars_per_batch

    def write_for_context(self, context: WorkflowContext) -> ReportSummary:
        design = self._resolve_design(context)
        brief = self._resolve_brief(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        research_design_id = design.id
        language = brief.language or design.language or "en"

        findings = self._finding_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        insights = self._insight_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not findings or not insights:
            raise ReportError(
                f"No run-scoped findings/insights available for report in run {workflow_run_id}",
            )

        evidence_items = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        sources = self._source_repository.list_for_project(project_id)
        run_sources = [
            item
            for item in sources
            if workflow_run_id in item.workflow_run_refs
        ]
        evidence_by_id = {item.id: item for item in evidence_items}
        sources_by_id = {item.id: item for item in run_sources}
        findings_by_id = {item.id: item for item in findings}
        insights_by_id = {item.id: item for item in insights}

        section_titles = resolve_section_titles(brief=brief, design=design)
        batches = batch_findings_by_question(
            list(findings),
            max_findings_per_batch=self._max_findings_per_batch,
            max_chars_per_batch=self._max_chars_per_batch,
        )

        validated_sections: list[ReportSection] = []
        sections_rejected = 0
        batch_failures = 0
        citation_registry = CitationRegistry()

        for batch_question_id, finding_batch in batches:
            batch_insights = insights_for_question(list(insights), batch_question_id)
            report_input = ReportInput(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                brief=brief,
                design=design,
                findings=tuple(finding_batch),
                insights=batch_insights,
                evidence_by_id=evidence_by_id,
                sources_by_id=sources_by_id,
                section_titles=section_titles,
                batch_question_id=(
                    None if batch_question_id == "__unscoped__" else batch_question_id
                ),
            )
            try:
                candidates = self._report_engine.generate_sections(report_input)
            except Exception:
                batch_failures += 1
                continue

            for candidate in candidates:
                try:
                    validated = validate_section_candidate(
                        candidate,
                        findings_by_id=findings_by_id,
                        insights_by_id=insights_by_id,
                        evidence_by_id=evidence_by_id,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        design=design,
                    )
                    evidence_refs = collect_evidence_refs_for_section(
                        validated,
                        findings_by_id=findings_by_id,
                        insights_by_id=insights_by_id,
                    )
                    citation_ids = citation_registry.citation_ids_for_evidence_refs(
                        evidence_refs,
                        evidence_by_id=evidence_by_id,
                        sources_by_id=sources_by_id,
                    )
                    validated_sections.append(
                        ReportSection(
                            id=str(uuid4()),
                            title=validated.title,
                            content=validated.content,
                            research_question_refs=validated.research_question_refs,
                            finding_refs=validated.finding_refs,
                            insight_refs=validated.insight_refs,
                            evidence_refs=evidence_refs,
                            citation_ids=citation_ids,
                            metadata=dict(validated.metadata or {}),
                        ),
                    )
                except InvalidReportProvenanceError:
                    sections_rejected += 1

        if not validated_sections:
            raise ReportError(
                f"No valid report sections produced for workflow run {workflow_run_id}",
            )

        summary_input = ReportInput(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            brief=brief,
            design=design,
            findings=tuple(findings),
            insights=tuple(insights),
            evidence_by_id=evidence_by_id,
            sources_by_id=sources_by_id,
            section_titles=section_titles,
            section_summaries=tuple(section.content for section in validated_sections),
        )
        section_candidates = tuple(
            ReportSectionCandidate(
                title=section.title,
                content=section.content,
                research_question_refs=section.research_question_refs,
                finding_refs=section.finding_refs,
                insight_refs=section.insight_refs,
                evidence_refs=section.evidence_refs,
            )
            for section in validated_sections
        )
        try:
            report_candidate = self._report_engine.generate_executive_summary(
                summary_input,
                sections=section_candidates,
            )
        except Exception as exc:
            raise ReportError(
                f"Executive summary generation failed for workflow run {workflow_run_id}",
            ) from exc

        title = report_candidate.title.strip() or brief.title or "Research Report"
        limitations = tuple(
            dict.fromkeys(
                [
                    *report_candidate.limitations,
                    *design.limitations,
                ],
            ),
        )
        generation_method = getattr(self._report_engine, "method_name", "unknown")
        revision_number = 1
        deduplication_key = compute_report_deduplication_key(
            workflow_run_id=workflow_run_id,
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=generation_method,
            revision_number=revision_number,
        )

        report_metadata = dict(report_candidate.metadata or {})
        scenario = context.read_shared("deterministic_review_scenario") or os.environ.get(
            "DETERMINISTIC_REVIEW_SCENARIO",
        )
        if scenario == "revise_once":
            report_metadata["deterministic_review_flaw"] = "unsupported_claim"
        elif scenario == "reject":
            report_metadata["deterministic_review_flaw"] = "provenance_break"

        finding_refs = tuple(sorted({ref for section in validated_sections for ref in section.finding_refs}))
        insight_refs = tuple(sorted({ref for section in validated_sections for ref in section.insight_refs}))
        evidence_refs = tuple(sorted({ref for section in validated_sections for ref in section.evidence_refs}))

        report_id = self._persist_report(
            report=Report(
                id=str(uuid4()),
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                title=title,
                language=language,
                sections=tuple(validated_sections),
                executive_summary=report_candidate.executive_summary.strip(),
                limitations=limitations,
                created_at=datetime.now(timezone.utc).isoformat(),
                generation_method=generation_method,
                finding_refs=finding_refs,
                insight_refs=insight_refs,
                evidence_refs=evidence_refs,
                citation_registry=citation_registry.to_dict(),
                deduplication_key=deduplication_key,
                revision_number=revision_number,
                approval_status="draft",
                metadata=report_metadata,
            ),
            workflow_run_id=workflow_run_id,
            deduplication_key=deduplication_key,
        )

        persisted_report = self._report_repository.get_by_id(report_id)
        if persisted_report is None:
            raise ReportError(f"Failed to load persisted report {report_id}")

        markdown = render_report_markdown(persisted_report)
        checksum = compute_content_checksum(markdown)
        artifact_dedup = compute_artifact_deduplication_key(
            workflow_run_id=workflow_run_id,
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        artifact_id = self._persist_artifact(
            artifact=ArtifactRecord(
                id=str(uuid4()),
                project_id=project_id,
                artifact_type="research_report",
                title=title,
                content=markdown,
                run_id=workflow_run_id,
                status="draft",
                media_type="text/markdown",
                filename=safe_report_filename(title),
                content_checksum=checksum,
                deduplication_key=artifact_dedup,
                report_id=report_id,
            ),
            workflow_run_id=workflow_run_id,
            deduplication_key=artifact_dedup,
        )

        return ReportSummary(
            report_id=report_id,
            artifact_id=artifact_id,
            section_count=len(validated_sections),
            sections_rejected=sections_rejected,
            batch_failures=batch_failures,
        )

    def revise_for_context(
        self,
        context: WorkflowContext,
        *,
        review_result: ReviewResult,
    ) -> ReportSummary:
        """Create a revised report revision addressing review issues (DR-07)."""
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        current = self._latest_report(project_id, workflow_run_id)
        if current is None:
            raise ReportError(f"No report to revise for run {workflow_run_id}")

        next_revision = current.revision_number + 1
        generation_method = current.generation_method
        deduplication_key = compute_report_deduplication_key(
            workflow_run_id=workflow_run_id,
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=generation_method,
            revision_number=next_revision,
        )

        revised_sections = []
        for section in current.sections:
            content = section.content
            if "UNSUPPORTED_CLAIM_MARKER" in content:
                content = content.replace("UNSUPPORTED_CLAIM_MARKER", "").strip()
            revised_sections.append(
                ReportSection(
                    id=str(uuid4()),
                    title=section.title,
                    content=content,
                    research_question_refs=section.research_question_refs,
                    finding_refs=section.finding_refs,
                    insight_refs=section.insight_refs,
                    evidence_refs=section.evidence_refs,
                    citation_ids=section.citation_ids,
                    metadata=dict(section.metadata),
                ),
            )

        metadata = dict(current.metadata)
        metadata.pop("deterministic_review_flaw", None)
        metadata["revision_of"] = current.id
        metadata["review_id"] = review_result.id

        revised_report = Report(
            id=str(uuid4()),
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=current.research_design_id,
            title=current.title,
            language=current.language,
            sections=tuple(revised_sections),
            executive_summary=current.executive_summary,
            limitations=current.limitations,
            created_at=datetime.now(timezone.utc).isoformat(),
            generation_method=generation_method,
            finding_refs=current.finding_refs,
            insight_refs=current.insight_refs,
            evidence_refs=current.evidence_refs,
            citation_registry=dict(current.citation_registry),
            deduplication_key=deduplication_key,
            revision_number=next_revision,
            previous_report_id=current.id,
            approval_status="draft",
            metadata=metadata,
        )

        report_id = self._persist_report(
            report=revised_report,
            workflow_run_id=workflow_run_id,
            deduplication_key=deduplication_key,
        )
        persisted_report = self._report_repository.get_by_id(report_id)
        if persisted_report is None:
            raise ReportError(f"Failed to load revised report {report_id}")

        markdown = render_report_markdown(persisted_report)
        checksum = compute_content_checksum(markdown)
        artifact_dedup = compute_artifact_deduplication_key(
            workflow_run_id=workflow_run_id,
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        existing_artifact = self._artifact_repository.get_by_deduplication_key(
            workflow_run_id,
            artifact_dedup,
        )
        if existing_artifact is None:
            raise ReportError(f"No draft artifact to revise for run {workflow_run_id}")

        updated_artifact = ArtifactRecord(
            id=existing_artifact.id,
            project_id=existing_artifact.project_id,
            artifact_type=existing_artifact.artifact_type,
            title=persisted_report.title,
            content=markdown,
            run_id=workflow_run_id,
            status="draft",
            version=existing_artifact.version,
            media_type=existing_artifact.media_type,
            filename=safe_report_filename(persisted_report.title),
            content_checksum=checksum,
            deduplication_key=artifact_dedup,
            report_id=report_id,
        )
        self._artifact_repository.save(
            updated_artifact,
            expected_version=existing_artifact.version,
        )

        return ReportSummary(
            report_id=report_id,
            artifact_id=existing_artifact.id,
            section_count=len(revised_sections),
            sections_rejected=0,
            batch_failures=0,
        )

    def _latest_report(self, project_id: str, workflow_run_id: str) -> Report | None:
        reports = self._report_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not reports:
            return None
        return max(reports, key=lambda item: item.revision_number)

    def _resolve_design(self, context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise ReportError("Workflow template is missing research_design_snapshot")
        return template.research_design_snapshot

    def _resolve_brief(self, context: WorkflowContext) -> ResearchBrief:
        template = context.workflow_template
        if template is None or template.research_brief_snapshot is None:
            raise ReportError("Workflow template is missing research_brief_snapshot")
        return template.research_brief_snapshot

    def _persist_report(
        self,
        *,
        report: Report,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> str:
        existing = self._report_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._report_repository.create(report)
                return report.id
            except DuplicateReportError:
                existing = self._report_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise ReportError(
            f"Failed to resolve concurrent report persistence for run {workflow_run_id}",
        )

    def _persist_artifact(
        self,
        *,
        artifact: ArtifactRecord,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> str:
        existing = self._artifact_repository.get_by_deduplication_key(
            workflow_run_id,
            deduplication_key,
        )
        if existing is not None:
            return existing.id

        for _ in range(_MAX_DEDUP_RETRIES):
            try:
                self._artifact_repository.create(artifact)
                return artifact.id
            except DuplicateArtifactError:
                existing = self._artifact_repository.get_by_deduplication_key(
                    workflow_run_id,
                    deduplication_key,
                )
                if existing is not None:
                    return existing.id

        raise ReportError(
            f"Failed to resolve concurrent artifact persistence for run {workflow_run_id}",
        )
