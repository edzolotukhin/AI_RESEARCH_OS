from __future__ import annotations

import logging
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
from application.evidence.temporal_scope import qualifying_evidence
from application.ports.analysis_ports import FindingRepository, InsightRepository
from application.ports.artifact_repository import ArtifactRepository
from application.ports.evidence_ports import EvidenceRepository
from application.ports.report_ports import ReportEngine, ReportInput, ReportRepository, ReportSectionCandidate
from application.ports.source_ports import SourceRepository
from application.report.citation_registry import CitationRegistry
from application.report.claim_scope_validation import validate_claim_scope
from application.report.content_batching import (
    batch_findings_by_question,
    insights_for_question,
    resolve_section_titles,
)
from application.report.coverage_validation import (
    enrich_research_question_refs,
    findings_available_for_question,
    missing_research_question_ids,
)
from application.report.report_assembly import (
    assemble_bounded_report,
    align_section_provenance,
    DEFAULT_REPORT_MAX_SECTIONS,
)
from application.report.substantive_coverage import (
    validate_mandatory_rq_candidate_binding,
    validate_mandatory_rq_bindings,
    validate_two_dimensional_coverage,
)
from application.report.structure_validation import validate_report_structure
from application.report.deduplication import (
    DR06_RESEARCH_REPORT_TYPE,
    compute_artifact_deduplication_key,
    compute_content_checksum,
    compute_report_deduplication_key,
)
from application.report.diagnostics import (
    FAILURE_CATEGORY_BATCH_ERROR,
    FAILURE_CATEGORY_LLM_ERROR,
    FAILURE_CATEGORY_PARSE_ERROR,
    FAILURE_CATEGORY_TRUNCATED_OUTPUT,
    ReportBatchDiagnostics,
    ReportFailureDiagnostics,
    classify_provenance_rejection,
    format_zero_sections_message,
)
from application.report.exceptions import (
    DuplicateArtifactError,
    DuplicateReportError,
    InvalidReportProvenanceError,
    ReportConfigurationError,
    ReportError,
)
from application.report.markdown_renderer import render_report_markdown, safe_report_filename
from application.report.provenance_validation import (
    collect_evidence_refs_for_section,
    validate_section_candidate,
)

from application.execution.exceptions import BudgetExhaustedError
from application.research_quality.analysis_coverage import coverage_snapshot_from_payload
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from runtime.workflow_context import WorkflowContext

logger = logging.getLogger("ai_research_os.report")

_MAX_DEDUP_RETRIES = 5
_MAX_REPAIR_DIAGNOSTIC_ATTEMPTS = 8
_MAX_REPAIR_DIAGNOSTIC_TARGETS = 16
_MAX_REPAIR_DIAGNOSTIC_IDS = 32
_MAX_REPAIR_DIAGNOSTIC_SECTIONS = 32
_MAX_REPAIR_DIAGNOSTIC_ERRORS = 32


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
        max_rq_correction_attempts: int = 2,
        max_sections: int = DEFAULT_REPORT_MAX_SECTIONS,
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
        self._max_rq_correction_attempts = max_rq_correction_attempts
        self._max_sections = max_sections

    def write_for_context(self, context: WorkflowContext) -> ReportSummary:
        design = self._resolve_design(context)
        brief = self._resolve_brief(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        research_design_id = design.id
        language = brief.language or design.language or "en"
        coverage = coverage_snapshot_from_payload(context.read_shared(SHARED_STATE_KEY))
        limited = coverage is not None and not coverage.complete_design_ready
        eligible_need_ids = set(
            coverage.eligible_information_need_ids if coverage is not None else ()
        )
        need_to_rq = {need.id: need.research_question_id for need in design.information_needs}
        eligible_rq_ids = tuple(sorted({need_to_rq[item] for item in eligible_need_ids}))
        allowed_rq_ids = eligible_rq_ids
        eligible_need_ids_without_findings: tuple[str, ...] = ()
        eligible_rq_ids_without_findings: tuple[str, ...] = ()

        findings = self._finding_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        insights = self._insight_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        if not findings:
            raise ReportError(
                f"No run-scoped findings available for report in run {workflow_run_id}",
            )
        if limited:
            findings = [
                item for item in findings
                if bool(item.information_need_refs)
                and set(item.information_need_refs) <= eligible_need_ids
            ]
            finding_ids = {item.id for item in findings}
            insights = [item for item in insights if set(item.finding_refs) <= finding_ids]
            if not findings:
                raise ReportError("Limited report has no eligible validated Findings")
            finding_backed_need_ids = {
                need_id
                for item in findings
                for need_id in item.information_need_refs
            }
            finding_backed_rq_ids = {
                rq_id
                for item in findings
                for rq_id in item.research_question_refs
            }
            allowed_rq_ids = tuple(sorted(finding_backed_rq_ids))
            eligible_need_ids_without_findings = tuple(
                sorted(eligible_need_ids - finding_backed_need_ids),
            )
            eligible_rq_ids_without_findings = tuple(
                sorted(set(eligible_rq_ids) - finding_backed_rq_ids),
            )

        evidence_items = self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
        )
        evidence_items = qualifying_evidence(
            design=design, evidence=evidence_items, brief=brief,
            source_repository=self._source_repository,
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
        mandatory_rq_findings = {
            rq_id: tuple(sorted(
                item.id for item in findings
                if rq_id in item.research_question_refs
            ))
            for rq_id in allowed_rq_ids
        } if limited else {}

        section_titles = resolve_section_titles(brief=brief, design=design)
        batches = batch_findings_by_question(
            list(findings),
            max_findings_per_batch=self._max_findings_per_batch,
            max_chars_per_batch=self._max_chars_per_batch,
        )

        validated_sections: list[ReportSection] = []
        section_batch_map: dict[str, str | None] = {}
        sections_rejected = 0
        batch_failures = 0
        batch_diagnostics: list[ReportBatchDiagnostics] = []
        citation_registry = CitationRegistry()

        for batch_question_id, finding_batch in batches:
            batch_insights = insights_for_question(list(insights), batch_question_id)
            batch_diag = ReportBatchDiagnostics(
                batch_question_id=(
                    None if batch_question_id == "__unscoped__" else batch_question_id
                ),
                input_finding_count=len(finding_batch),
                input_insight_count=len(batch_insights),
            )
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
                coverage_snapshot=coverage.to_dict() if coverage is not None else None,
                mandatory_substantive_rq_findings=mandatory_rq_findings,
            )
            try:
                candidates = self._report_engine.generate_sections(report_input)
            except BudgetExhaustedError as exc:
                raise ReportError(str(exc)) from exc
            except ReportConfigurationError as exc:
                batch_failures += 1
                batch_diag.failure_category = _classify_batch_failure(exc)
                batch_diag.parse_failure_category = _parse_failure_from_engine(
                    self._report_engine,
                )
                _apply_engine_telemetry(batch_diag, self._report_engine)
                batch_diagnostics.append(batch_diag)
                logger.warning(
                    "report_batch_failed",
                    extra={
                        "event": "report_batch_failed",
                        "workflow_run_id": workflow_run_id,
                        "batch_question_id": batch_diag.batch_question_id,
                        "failure_category": batch_diag.failure_category,
                        **batch_diag.to_dict(),
                    },
                )
                continue
            except Exception as exc:
                batch_failures += 1
                batch_diag.failure_category = FAILURE_CATEGORY_BATCH_ERROR
                batch_diagnostics.append(batch_diag)
                logger.exception(
                    "report_batch_failed",
                    extra={
                        "event": "report_batch_failed",
                        "workflow_run_id": workflow_run_id,
                        "batch_question_id": batch_diag.batch_question_id,
                        "failure_category": batch_diag.failure_category,
                    },
                )
                continue

            engine_stats = getattr(self._report_engine, "last_section_batch_stats", None)
            if engine_stats is not None:
                batch_diag.candidate_section_count = engine_stats.candidate_section_count
                batch_diag.engine_dropped_count = engine_stats.engine_dropped_count
                batch_diag.rejection_counts.update(engine_stats.rejection_counts)
                batch_diag.output_tokens = engine_stats.output_tokens
                batch_diag.reasoning_tokens = engine_stats.reasoning_tokens
                batch_diag.visible_output_length = engine_stats.visible_output_length
                batch_diag.finish_reason = engine_stats.finish_reason
                batch_diag.max_output_tokens = engine_stats.max_output_tokens
                batch_diag.reasoning_effort = engine_stats.reasoning_effort
                batch_diag.parse_failure_category = engine_stats.parse_failure_category

            for candidate in candidates:
                binding_errors = validate_mandatory_rq_candidate_binding(
                    candidate,
                    mandatory_rq_findings=mandatory_rq_findings,
                )
                if binding_errors:
                    batch_diag.rejected_section_count += 1
                    for error in binding_errors:
                        batch_diag.rejection_counts[error] = (
                            batch_diag.rejection_counts.get(error, 0) + 1
                        )
                    sections_rejected += 1
                    continue
                added = self._append_validated_section(
                    candidate,
                    validated_sections=validated_sections,
                    section_batch_map=section_batch_map,
                    batch_question_id=batch_question_id,
                    findings_by_id=findings_by_id,
                    insights_by_id=insights_by_id,
                    evidence_by_id=evidence_by_id,
                    sources_by_id=sources_by_id,
                    citation_registry=citation_registry,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    design=design,
                    batch_diag=batch_diag,
                    allowed_research_question_ids=(allowed_rq_ids if limited else None),
                )
                if not added:
                    sections_rejected += 1

            batch_diagnostics.append(batch_diag)

        if not validated_sections:
            failure_diagnostics = ReportFailureDiagnostics(
                workflow_run_id=workflow_run_id,
                finding_count=len(findings),
                insight_count=len(insights),
                batch_count=len(batches),
                batch_failures=batch_failures,
                sections_rejected=sections_rejected,
                batches=batch_diagnostics,
            )
            logger.error(
                "report_zero_sections",
                extra={
                    "event": "report_zero_sections",
                    **failure_diagnostics.to_dict(),
                },
            )
            raise ReportError(format_zero_sections_message(failure_diagnostics))

        if not limited:
            self._correct_missing_research_question_coverage(
                validated_sections=validated_sections,
                section_batch_map=section_batch_map,
                findings=findings,
                insights=insights,
                evidence_by_id=evidence_by_id,
                sources_by_id=sources_by_id,
                findings_by_id=findings_by_id,
                insights_by_id=insights_by_id,
                citation_registry=citation_registry,
                brief=brief,
                design=design,
                section_titles=section_titles,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
            )

        validated_sections = list(
            assemble_bounded_report(
                validated_sections,
                design=design,
                findings=findings,
                limitations=tuple(design.limitations),
                max_sections=self._max_sections,
                section_batch_map=section_batch_map,
            ),
        )
        registry_dict = citation_registry.to_dict()
        aligned_sections: list[ReportSection] = []
        for section in validated_sections:
            aligned_sections.append(
                align_section_provenance(
                    section,
                    findings_by_id=findings_by_id,
                    registry=registry_dict,
                ),
            )
        validated_sections = aligned_sections
        section_batch_map = {
            section.id: (section.metadata or {}).get("primary_research_question_id")
            for section in validated_sections
        }

        coverage_errors = validate_two_dimensional_coverage(
            validated_sections,
            findings=findings,
            insights=insights,
            design=design,
            section_batch_map=section_batch_map,
            required_research_question_ids=(allowed_rq_ids if limited else None),
        )
        coverage_errors = (
            *coverage_errors,
            *validate_mandatory_rq_bindings(
                validated_sections,
                mandatory_rq_findings=mandatory_rq_findings,
            ),
        )
        repair_attempts: list[dict[str, Any]] = []
        if limited and coverage_errors:
            repair_errors = tuple(
                error for error in coverage_errors
                if error.startswith("substantive_coverage_missing:")
                or error.startswith("mandatory_rq_finding_binding_missing:")
            )
            if repair_errors:
                repair_attempts = self._repair_limited_mandatory_coverage(
                    validated_sections=validated_sections,
                    section_batch_map=section_batch_map,
                    findings=findings,
                    insights=insights,
                    evidence_by_id=evidence_by_id,
                    sources_by_id=sources_by_id,
                    findings_by_id=findings_by_id,
                    insights_by_id=insights_by_id,
                    citation_registry=citation_registry,
                    brief=brief,
                    design=design,
                    section_titles=section_titles,
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    coverage_snapshot=coverage.to_dict() if coverage is not None else None,
                    mandatory_rq_findings=mandatory_rq_findings,
                    diagnostics=repair_errors,
                )
                validated_sections = list(assemble_bounded_report(
                    validated_sections,
                    design=design,
                    findings=findings,
                    limitations=tuple(design.limitations),
                    max_sections=self._max_sections,
                    section_batch_map=section_batch_map,
                ))
                validated_sections = [
                    align_section_provenance(
                        section,
                        findings_by_id=findings_by_id,
                        registry=citation_registry.to_dict(),
                    )
                    for section in validated_sections
                ]
                section_batch_map = {
                    section.id: (section.metadata or {}).get("primary_research_question_id")
                    for section in validated_sections
                }
                coverage_errors = (
                    *validate_two_dimensional_coverage(
                        validated_sections,
                        findings=findings,
                        insights=insights,
                        design=design,
                        section_batch_map=section_batch_map,
                        required_research_question_ids=allowed_rq_ids,
                    ),
                    *validate_mandatory_rq_bindings(
                        validated_sections,
                        mandatory_rq_findings=mandatory_rq_findings,
                    ),
                )
                for attempt in repair_attempts:
                    attempt["post_validation_errors"] = list(coverage_errors)[
                        :_MAX_REPAIR_DIAGNOSTIC_ERRORS
                    ]
                context.write_shared(
                    "report_repair_diagnostics",
                    {"version": 1, "attempts": repair_attempts},
                )
        if coverage_errors:
            context.write_shared(
                "report_generation_diagnostics",
                {
                    "phase": "coverage_validation",
                    "mandatory_substantive_rq_findings": {
                        key: list(value) for key, value in mandatory_rq_findings.items()
                    },
                    "finding_evidence_refs": {
                        finding_id: list(findings_by_id[finding_id].evidence_refs)
                        for finding_ids in mandatory_rq_findings.values()
                        for finding_id in finding_ids
                        if finding_id in findings_by_id
                    },
                    "generated_sections": [
                        {
                            "id": section.id,
                            "research_question_refs": list(section.research_question_refs),
                            "finding_refs": list(section.finding_refs),
                        }
                        for section in validated_sections
                    ],
                    "rejection_reasons": list(coverage_errors),
                },
            )
            raise ReportError(
                f"Report coverage validation failed for run {workflow_run_id}: "
                f"{list(coverage_errors)}",
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
            coverage_snapshot=coverage.to_dict() if coverage is not None else None,
            mandatory_substantive_rq_findings=mandatory_rq_findings,
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
                    *(
                        _coverage_limitations(
                            coverage,
                            eligible_need_ids_without_findings=(
                                eligible_need_ids_without_findings
                            ),
                            eligible_rq_ids_without_findings=(
                                eligible_rq_ids_without_findings
                            ),
                        )
                        if limited else ()
                    ),
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
        if limited and report_metadata.get("report_scope") == "complete":
            raise ReportError("Limited report must not claim complete research")
        if coverage is not None:
            report_metadata.update(coverage.to_dict())
        scenario = context.read_shared("deterministic_review_scenario") or os.environ.get(
            "DETERMINISTIC_REVIEW_SCENARIO",
        )
        if scenario == "revise_once":
            report_metadata["deterministic_review_flaw"] = "unsupported_claim"
        elif scenario == "reject":
            report_metadata["deterministic_review_flaw"] = "provenance_break"

        structure_errors = validate_report_structure(
            sections=tuple(validated_sections),
            executive_summary=report_candidate.executive_summary.strip(),
            limitations=limitations,
            design=design,
            findings=findings,
        )
        if structure_errors:
            raise ReportError(
                f"Report structure validation failed for run {workflow_run_id}: "
                f"{list(structure_errors)}",
            )

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

    def _append_validated_section(
        self,
        candidate: ReportSectionCandidate,
        *,
        validated_sections: list[ReportSection],
        section_batch_map: dict[str, str | None],
        batch_question_id: str,
        findings_by_id: dict,
        insights_by_id: dict,
        evidence_by_id: dict,
        sources_by_id: dict,
        citation_registry: CitationRegistry,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        design: ResearchDesign,
        batch_diag: ReportBatchDiagnostics,
        allowed_research_question_ids: tuple[str, ...] | None = None,
    ) -> bool:
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
                allowed_research_question_ids=allowed_research_question_ids,
            )
            question_refs = enrich_research_question_refs(
                validated,
                batch_question_id=(
                    None if batch_question_id == "__unscoped__" else batch_question_id
                ),
                findings_by_id=findings_by_id,
                insights_by_id=insights_by_id,
                design=design,
            )
            validated = ReportSectionCandidate(
                title=validated.title,
                content=validated.content,
                research_question_refs=question_refs,
                finding_refs=validated.finding_refs,
                insight_refs=validated.insight_refs,
                evidence_refs=validated.evidence_refs,
                metadata=dict(validated.metadata or {}),
            )
            metadata = dict(validated.metadata or {})
            if batch_question_id and batch_question_id != "__unscoped__":
                metadata["primary_research_question_id"] = batch_question_id
                metadata["batch_question_id"] = batch_question_id
            evidence_refs = collect_evidence_refs_for_section(
                validated,
                findings_by_id=findings_by_id,
                insights_by_id=insights_by_id,
            )
            scope_errors = validate_claim_scope(
                validated.content,
                finding_ids=(
                    *validated.finding_refs,
                    *tuple(
                        finding_id
                        for insight_id in validated.insight_refs
                        for finding_id in insights_by_id[insight_id].finding_refs
                        if insight_id in insights_by_id
                    ),
                ),
                findings_by_id=findings_by_id,
                insights_by_id=insights_by_id,
                evidence_by_id=evidence_by_id,
            )
            if scope_errors:
                batch_diag.rejected_section_count += 1
                batch_diag.rejection_counts["claim_scope"] = (
                    batch_diag.rejection_counts.get("claim_scope", 0) + 1
                )
                return False
            citation_ids = citation_registry.citation_ids_for_evidence_refs(
                evidence_refs,
                evidence_by_id=evidence_by_id,
                sources_by_id=sources_by_id,
            )
            if _section_requires_citations(
                evidence_refs,
                evidence_by_id=evidence_by_id,
                sources_by_id=sources_by_id,
            ) and not citation_ids:
                batch_diag.rejected_section_count += 1
                batch_diag.rejection_counts["missing_citation"] = (
                    batch_diag.rejection_counts.get("missing_citation", 0) + 1
                )
                return False
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
                    metadata=metadata,
                ),
            )
            section_batch_map[validated_sections[-1].id] = (
                None if batch_question_id == "__unscoped__" else batch_question_id
            )
            batch_diag.valid_section_count += 1
            return True
        except InvalidReportProvenanceError as exc:
            batch_diag.rejected_section_count += 1
            category = classify_provenance_rejection(exc)
            batch_diag.rejection_counts[category] = (
                batch_diag.rejection_counts.get(category, 0) + 1
            )
            return False

    def _repair_limited_mandatory_coverage(
        self,
        *,
        validated_sections: list[ReportSection],
        section_batch_map: dict[str, str | None],
        findings: list,
        insights: list,
        evidence_by_id: dict,
        sources_by_id: dict,
        findings_by_id: dict,
        insights_by_id: dict,
        citation_registry: CitationRegistry,
        brief: ResearchBrief,
        design: ResearchDesign,
        section_titles: tuple[str, ...],
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        coverage_snapshot: dict | None,
        mandatory_rq_findings: dict[str, tuple[str, ...]],
        diagnostics: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """Bounded repair for authoritative limited-report RQ omissions."""
        attempts: list[dict[str, Any]] = []
        for attempt_number in range(1, self._max_rq_correction_attempts + 1):
            missing = tuple(
                rq_id for rq_id, finding_ids in sorted(mandatory_rq_findings.items())
                if finding_ids and not any(
                    rq_id in section.research_question_refs
                    and set(finding_ids).intersection(section.finding_refs)
                    for section in validated_sections
                )
            )
            if not missing:
                break
            progressed = False
            attempt_diag: dict[str, Any] = {
                "attempt": attempt_number,
                "targets": [],
                "post_merge": {},
                "post_validation_errors": [],
            }
            for question_id in missing:
                finding_batch = [
                    finding for finding in findings
                    if question_id in finding.research_question_refs
                ]
                if not finding_batch:
                    continue
                target_diag = {
                    "rq_id": question_id,
                    "finding_ids": sorted(mandatory_rq_findings[question_id])[
                        :_MAX_REPAIR_DIAGNOSTIC_IDS
                    ],
                    "finding_support": {
                        finding.id: sorted(finding.evidence_refs)
                        [:_MAX_REPAIR_DIAGNOSTIC_IDS]
                        for finding in finding_batch[:_MAX_REPAIR_DIAGNOSTIC_IDS]
                        if finding.id in mandatory_rq_findings[question_id]
                    },
                    "triggering_errors": list(diagnostics)[
                        :_MAX_REPAIR_DIAGNOSTIC_ERRORS
                    ],
                }
                if len(attempt_diag["targets"]) < _MAX_REPAIR_DIAGNOSTIC_TARGETS:
                    attempt_diag["targets"].append(target_diag)
                report_input = ReportInput(
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    brief=brief,
                    design=design,
                    findings=tuple(finding_batch),
                    insights=insights_for_question(list(insights), question_id),
                    evidence_by_id=evidence_by_id,
                    sources_by_id=sources_by_id,
                    section_titles=section_titles,
                    batch_question_id=question_id,
                    coverage_snapshot=coverage_snapshot,
                    mandatory_substantive_rq_findings={
                        question_id: mandatory_rq_findings[question_id],
                    },
                    repair_diagnostics=diagnostics,
                )
                try:
                    candidates = self._report_engine.generate_sections(report_input)
                except Exception:
                    if target_diag in attempt_diag["targets"]:
                        target_diag["generator_status"] = "error"
                    continue
                target_diag["generator_status"] = "ok"
                target_diag["candidate_sections"] = [
                    {
                        "candidate_index": index,
                        "section_id": (
                            candidate.metadata.get("section_id")
                            if isinstance(candidate.metadata, dict)
                            and isinstance(candidate.metadata.get("section_id"), str)
                            else None
                        ),
                        "research_question_refs": sorted(candidate.research_question_refs),
                        "finding_refs": sorted(candidate.finding_refs),
                        "support_refs": sorted(candidate.evidence_refs),
                        "body_non_empty": bool(candidate.content.strip()),
                        "schema_status": "parsed",
                    }
                    for index, candidate in list(enumerate(candidates))[
                        :_MAX_REPAIR_DIAGNOSTIC_SECTIONS
                    ]
                ]
                batch_diag = ReportBatchDiagnostics(
                    batch_question_id=question_id,
                    input_finding_count=len(finding_batch),
                    input_insight_count=len(report_input.insights),
                )
                for candidate in candidates:
                    if validate_mandatory_rq_candidate_binding(
                        candidate,
                        mandatory_rq_findings={
                            question_id: mandatory_rq_findings[question_id],
                        },
                    ):
                        continue
                    if self._append_validated_section(
                        candidate,
                        validated_sections=validated_sections,
                        section_batch_map=section_batch_map,
                        batch_question_id=question_id,
                        findings_by_id=findings_by_id,
                        insights_by_id=insights_by_id,
                        evidence_by_id=evidence_by_id,
                        sources_by_id=sources_by_id,
                        citation_registry=citation_registry,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        design=design,
                        batch_diag=batch_diag,
                    ):
                        progressed = True
                if (
                    question_id in attempt_diag["post_merge"]
                    or len(attempt_diag["post_merge"]) < _MAX_REPAIR_DIAGNOSTIC_TARGETS
                ):
                    attempt_diag["post_merge"][question_id] = [
                        {
                            "section_id": section.id,
                            "research_question_refs": sorted(section.research_question_refs),
                            "finding_refs": sorted(section.finding_refs),
                            "support_refs": sorted(section.evidence_refs),
                        }
                        for section in validated_sections
                        if question_id in section.research_question_refs
                    ][:_MAX_REPAIR_DIAGNOSTIC_SECTIONS]
            attempts.append(attempt_diag)
            attempts = attempts[:_MAX_REPAIR_DIAGNOSTIC_ATTEMPTS]
            if not progressed:
                break
        return attempts[:_MAX_REPAIR_DIAGNOSTIC_ATTEMPTS]

    def _correct_missing_research_question_coverage(
        self,
        *,
        validated_sections: list[ReportSection],
        section_batch_map: dict[str, str | None],
        findings: list,
        insights: list,
        evidence_by_id: dict,
        sources_by_id: dict,
        findings_by_id: dict,
        insights_by_id: dict,
        citation_registry: CitationRegistry,
        brief: ResearchBrief,
        design: ResearchDesign,
        section_titles: tuple[str, ...],
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
    ) -> None:
        for _ in range(self._max_rq_correction_attempts):
            missing = missing_research_question_ids(
                validated_sections,
                findings=findings,
                design=design,
            )
            if not missing:
                return

            progressed = False
            for question_id in missing:
                finding_batch = findings_available_for_question(findings, question_id)
                if not finding_batch:
                    continue
                batch_insights = insights_for_question(list(insights), question_id)
                report_input = ReportInput(
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    brief=brief,
                    design=design,
                    findings=finding_batch,
                    insights=batch_insights,
                    evidence_by_id=evidence_by_id,
                    sources_by_id=sources_by_id,
                    section_titles=section_titles,
                    batch_question_id=question_id,
                )
                try:
                    candidates = self._report_engine.generate_sections(report_input)
                except (ReportConfigurationError, Exception):
                    logger.warning(
                        "report_rq_correction_failed",
                        extra={
                            "event": "report_rq_correction_failed",
                            "workflow_run_id": workflow_run_id,
                            "research_question_id": question_id,
                        },
                    )
                    continue

                batch_diag = ReportBatchDiagnostics(
                    batch_question_id=question_id,
                    input_finding_count=len(finding_batch),
                    input_insight_count=len(batch_insights),
                )
                for candidate in candidates:
                    if self._append_validated_section(
                        candidate,
                        validated_sections=validated_sections,
                        section_batch_map=section_batch_map,
                        batch_question_id=question_id,
                        findings_by_id=findings_by_id,
                        insights_by_id=insights_by_id,
                        evidence_by_id=evidence_by_id,
                        sources_by_id=sources_by_id,
                        citation_registry=citation_registry,
                        project_id=project_id,
                        workflow_run_id=workflow_run_id,
                        research_design_id=research_design_id,
                        design=design,
                        batch_diag=batch_diag,
                    ):
                        progressed = True

            if not progressed:
                return


def _section_requires_citations(
    evidence_refs: tuple[str, ...],
    *,
    evidence_by_id: dict,
    sources_by_id: dict,
) -> bool:
    for evidence_id in evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is not None and evidence.source_id in sources_by_id:
            return True
    return False


def _coverage_limitations(
    coverage,
    *,
    eligible_need_ids_without_findings: tuple[str, ...] = (),
    eligible_rq_ids_without_findings: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if coverage is None or coverage.complete_design_ready:
        return ()
    payload = coverage.to_dict()
    limitations = ["Research coverage is limited; the complete Design is not ready."]
    for label, key in (
        ("Partial InformationNeeds", "partial_information_need_ids"),
        ("Insufficient InformationNeeds", "insufficient_information_need_ids"),
        ("Missing InformationNeeds", "missing_information_need_ids"),
        ("Blocked InformationNeeds", "blocked_information_need_ids"),
    ):
        values = payload.get(key) or []
        if values:
            limitations.append(f"{label}: {', '.join(values)}.")
    for need_id, aspects in (payload.get("missing_required_aspect_refs") or {}).items():
        if aspects:
            limitations.append(
                f"Missing required aspects for {need_id}: {', '.join(aspects)}."
            )
    if payload.get("source_diversity_limited_information_need_ids"):
        limitations.append(
            "Source-diversity limitations: "
            + ", ".join(payload["source_diversity_limited_information_need_ids"])
            + "."
        )
    if eligible_need_ids_without_findings:
        limitations.append(
            "Analysis-eligible InformationNeeds without validated Findings: "
            + ", ".join(eligible_need_ids_without_findings)
            + "."
        )
    if eligible_rq_ids_without_findings:
        limitations.append(
            "ResearchQuestions without validated Findings: "
            + ", ".join(eligible_rq_ids_without_findings)
            + "."
        )
    return tuple(limitations)


def _classify_batch_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if "structured output" in message or "json" in message or "parse" in message:
        return FAILURE_CATEGORY_PARSE_ERROR
    if "truncated" in message:
        return FAILURE_CATEGORY_TRUNCATED_OUTPUT
    return FAILURE_CATEGORY_LLM_ERROR


def _parse_failure_from_engine(report_engine) -> str | None:
    engine_stats = getattr(report_engine, "last_section_batch_stats", None)
    if engine_stats is not None and engine_stats.parse_failure_category:
        return engine_stats.parse_failure_category
    structured = getattr(report_engine, "_structured_output", None)
    telemetry = getattr(structured, "last_telemetry", None)
    if telemetry is not None:
        return telemetry.parse_failure_category
    return None


def _apply_engine_telemetry(batch_diag: ReportBatchDiagnostics, report_engine) -> None:
    engine_stats = getattr(report_engine, "last_section_batch_stats", None)
    if engine_stats is None:
        return
    batch_diag.output_tokens = engine_stats.output_tokens
    batch_diag.reasoning_tokens = engine_stats.reasoning_tokens
    batch_diag.visible_output_length = engine_stats.visible_output_length
    batch_diag.finish_reason = engine_stats.finish_reason
    batch_diag.max_output_tokens = engine_stats.max_output_tokens
    batch_diag.reasoning_effort = engine_stats.reasoning_effort
    batch_diag.parse_failure_category = engine_stats.parse_failure_category
