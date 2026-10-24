from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from application.evidence.temporal_scope import qualifying_evidence
from application.persistence.records import ArtifactRecord
from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from application.report.citation_registry import CitationRegistry
from application.report.claim_coverage import validate_claim_backed_coverage
from application.report.claim_generation import ClaimGenerationError, generate_validated_claims
from application.report.claim_rendering import ClaimRenderingError, render_validated_claims, repair_missing_claim_sections
from application.report.coverage_contract import CONTRACT_KEY, build_report_coverage_contract, excluded_rq_limitation
from application.report.deduplication import DR06_RESEARCH_REPORT_TYPE, compute_artifact_deduplication_key, compute_content_checksum, compute_report_deduplication_key
from application.report.exceptions import ReportError
from application.report.markdown_renderer import render_report_markdown, safe_report_filename
from application.report.report_service import ReportService, ReportSummary
from application.research_quality.analysis_coverage import coverage_snapshot_from_payload
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from domain.reports.report import Report
from runtime.workflow_context import WorkflowContext


class ClaimFirstReportService(ReportService):
    """New Desk path: authority -> claims -> prose; legacy methods stay readable."""

    def __init__(self, *, report_claim_repository: ReportClaimRepository, **kwargs) -> None:
        super().__init__(**kwargs)
        self._report_claim_repository = report_claim_repository

    def write_for_context(self, context: WorkflowContext) -> ReportSummary:
        context.write_shared("report_generation_diagnostics", {"version": 2, "phase": "claim_generation", "status": "started", "workflow_run_id": context.workflow_run.id})
        design = self._resolve_design(context); brief = self._resolve_brief(context)
        project_id = context.project.id; report_run_id = context.workflow_run.id
        from application.replay.desk_downstream_replay import source_run_id
        source_run = source_run_id(context)
        coverage = coverage_snapshot_from_payload(context.read_shared(SHARED_STATE_KEY))
        limited = coverage is not None and not coverage.complete_design_ready
        findings = self._finding_repository.list_for_project(project_id, workflow_run_id=source_run)
        insights = self._insight_repository.list_for_project(project_id, workflow_run_id=source_run)
        if not findings:
            raise ReportError(f"No run-scoped findings available for report in run {report_run_id}")
        if limited:
            eligible_needs = set(coverage.eligible_information_need_ids)
            findings = [item for item in findings if item.information_need_refs and set(item.information_need_refs) <= eligible_needs]
            finding_ids = {item.id for item in findings}
            insights = [item for item in insights if set(item.finding_refs) <= finding_ids]
            if not findings:
                raise ReportError("Limited report has no eligible validated Findings")
        evidence = qualifying_evidence(design=design, evidence=self._evidence_repository.list_for_project(project_id, workflow_run_id=source_run), brief=brief, source_repository=self._source_repository)
        evidence_by_id = {item.id: item for item in evidence}
        sources = [item for item in self._source_repository.list_for_project(project_id) if source_run in item.workflow_run_refs]
        sources_by_id = {item.id: item for item in sources}
        registry = CitationRegistry()
        for item in evidence:
            registry.register_evidence(item, sources_by_id=sources_by_id)
        source_to_citation = {entry["source_id"]: citation_id for citation_id, entry in registry.to_dict().items()}
        required = tuple(sorted({rq for item in findings for rq in item.research_question_refs})) if limited else tuple(sorted(question.id for question in design.research_questions))
        contract = build_report_coverage_contract(design=design, limited=limited, required_rq_ids=required)
        mandatory = {rq: tuple(sorted(item.id for item in findings if rq in item.research_question_refs)) for rq in contract.required_rq_ids}
        try:
            claims = generate_validated_claims(project_id=project_id, source_workflow_run_id=source_run, report_workflow_run_id=report_run_id, design=design, findings=tuple(findings), insights=tuple(insights), evidence_by_id=evidence_by_id, citation_id_by_source=source_to_citation)
            rendered = render_validated_claims(claims=claims, design=design)
        except (ClaimGenerationError, ClaimRenderingError, ValueError) as exc:
            context.write_shared("report_generation_diagnostics", {"version": 2, "phase": "claim_first_validation", "status": "failed", "workflow_run_id": report_run_id, "source_run_id": source_run, "category": type(exc).__name__})
            raise ReportError(f"Claim-first Report generation failed for run {report_run_id}") from exc
        sections = rendered.sections
        errors = validate_claim_backed_coverage(claims=claims, sections=sections, contract=contract, mandatory_rq_findings=mandatory)
        if errors:
            sections = repair_missing_claim_sections(sections=sections, claims=claims, required_rq_ids=contract.required_rq_ids, design=design)
            errors = validate_claim_backed_coverage(claims=claims, sections=sections, contract=contract, mandatory_rq_findings=mandatory)
        if errors:
            context.write_shared("report_generation_diagnostics", {"version": 2, "phase": "claim_coverage", "status": "failed", "rejection_reasons": list(errors)})
            raise ReportError(f"Claim-backed Report coverage failed for run {report_run_id}: {list(errors)}")
        excluded = excluded_rq_limitation(contract)
        limitations = tuple(dict.fromkeys([*design.limitations, *((excluded,) if excluded else ())]))
        method = f"claim-first:{getattr(self._report_engine, 'method_name', 'unknown')}"
        revision = 1
        dedup = compute_report_deduplication_key(workflow_run_id=report_run_id, report_type=DR06_RESEARCH_REPORT_TYPE, generation_method=method, revision_number=revision)
        metadata = {CONTRACT_KEY: contract.to_metadata(), "report_scope": contract.mode, "structured_claim_contract": "desk_report_claim_v1", "summary_units": list(rendered.summary_units)}
        if coverage is not None: metadata.update(coverage.to_dict())
        report = Report(id=str(uuid4()), project_id=project_id, workflow_run_id=report_run_id, research_design_id=design.id, title=brief.title or "Desk Research Report", language=brief.language or design.language or "en", sections=sections, executive_summary=rendered.executive_summary, limitations=limitations, created_at=datetime.now(timezone.utc).isoformat(), generation_method=method, finding_refs=tuple(sorted({ref for claim in claims for ref in claim.finding_ids})), insight_refs=tuple(sorted({ref for claim in claims for ref in claim.insight_ids})), evidence_refs=tuple(sorted({ref for claim in claims for ref in claim.evidence_ids})), citation_registry=registry.to_dict(), deduplication_key=dedup, revision_number=revision, approval_status="draft", metadata=metadata)
        existing = self._report_repository.get_by_deduplication_key(report_run_id, dedup)
        if existing is None:
            try: self._report_claim_repository.create_with_report(report, claims)
            except ReportClaimConflictError as exc: raise ReportError("Atomic structured Report persistence failed") from exc
            report_id = report.id
        else:
            stored_claims = self._report_claim_repository.list_for_report(existing.id, existing.revision_number)
            if not stored_claims: raise ReportError("Structured Report exists without required ReportClaims")
            report_id = existing.id
        persisted = self._report_repository.get_by_id(report_id)
        if persisted is None: raise ReportError(f"Failed to load persisted report {report_id}")
        markdown = render_report_markdown(persisted); checksum = compute_content_checksum(markdown)
        artifact_dedup = compute_artifact_deduplication_key(workflow_run_id=report_run_id, artifact_type=DR06_RESEARCH_REPORT_TYPE)
        artifact_id = self._persist_artifact(artifact=ArtifactRecord(id=str(uuid4()), project_id=project_id, artifact_type="research_report", title=persisted.title, content=markdown, run_id=report_run_id, status="draft", media_type="text/markdown", filename=safe_report_filename(persisted.title), content_checksum=checksum, deduplication_key=artifact_dedup, report_id=report_id), workflow_run_id=report_run_id, deduplication_key=artifact_dedup)
        context.write_shared("report_generation_diagnostics", {"version": 2, "phase": "persisted", "status": "completed", "workflow_run_id": report_run_id, "source_run_id": source_run, "report_id": report_id, "claim_count": len(claims)})
        return ReportSummary(report_id=report_id, artifact_id=artifact_id, section_count=len(sections), sections_rejected=0, batch_failures=0)
