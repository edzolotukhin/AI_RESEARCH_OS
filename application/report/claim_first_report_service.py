from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from application.evidence.temporal_scope import qualifying_evidence
from application.persistence.records import ArtifactRecord
from application.ports.report_claim_repository import ReportClaimConflictError, ReportClaimRepository
from application.report.citation_registry import CitationRegistry
from application.report.claim_coverage import validate_claim_backed_coverage
from application.report.claim_generation import ClaimGenerationError, generate_validated_claims
from application.report.claim_rendering import ClaimRenderingError, render_validated_claims, repair_missing_claim_sections
from application.report.claim_authority import derive_claim_authority
from application.report.claim_validation import validate_report_claim
from application.report.coverage_contract import CONTRACT_KEY, build_report_coverage_contract, excluded_rq_limitation, resolve_report_coverage_contract
from application.report.deduplication import DR06_RESEARCH_REPORT_TYPE, compute_artifact_deduplication_key, compute_content_checksum, compute_report_deduplication_key
from application.report.exceptions import ReportError
from application.report.markdown_renderer import render_report_markdown, safe_report_filename
from application.report.editorial_composer import EditorialComposer, EditorialCompositionError
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION, build_authorized_editorial_catalog
from application.report.presentation_persistence import (
    attach_editorial_envelope,
    presentation_report_digest,
    read_presentation_report,
    report_claims_authority_digest,
)
from application.report.report_service import ReportService, ReportSummary
from application.research_quality.analysis_coverage import coverage_snapshot_from_payload
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim
from domain.reviews.review_result import ReviewResult
from runtime.workflow_context import WorkflowContext


class ClaimFirstReportService(ReportService):
    """New Desk path: authority -> claims -> prose; legacy methods stay readable."""

    def __init__(
        self, *, report_claim_repository: ReportClaimRepository,
        report_contract_version: str = "desk_report_claim_v1",
        editorial_composer: EditorialComposer | None = None,
        **kwargs,
    ) -> None:
        report_engine = kwargs.get("report_engine")
        super().__init__(**kwargs)
        if report_contract_version not in {"desk_report_claim_v1", EDITORIAL_CONTRACT_VERSION}:
            raise ValueError("unsupported Report contract version")
        if report_contract_version == EDITORIAL_CONTRACT_VERSION and editorial_composer is None:
            raise ValueError("desk_editorial_v1 requires an EditorialComposer")
        self._report_claim_repository = report_claim_repository
        self._report_contract_version = report_contract_version
        self._editorial_composer = editorial_composer
        self._claim_candidate_provider = getattr(
            report_engine, "generate_claim_candidates", None,
        )
        self._claim_correction_provider = getattr(
            report_engine, "repair_claim_candidates", None,
        )

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
            if (
                getattr(self._report_engine, "method_name", "") == "llm"
                and not callable(self._claim_candidate_provider)
            ):
                raise ClaimGenerationError(
                    "ReportClaim initial provider is not configured",
                    diagnostics={
                        "category": "provider_not_configured",
                        "failure_stage": "initial_provider_configuration",
                        "attempt_count": 0,
                    },
                )
            claims = generate_validated_claims(
                project_id=project_id,
                source_workflow_run_id=source_run,
                report_workflow_run_id=report_run_id,
                design=design,
                findings=tuple(findings),
                insights=tuple(insights),
                evidence_by_id=evidence_by_id,
                citation_id_by_source=source_to_citation,
                candidate_provider=self._claim_candidate_provider,
                correction_provider=self._claim_correction_provider,
            )
            rendered = render_validated_claims(claims=claims, design=design)
        except (ClaimGenerationError, ClaimRenderingError, ValueError) as exc:
            diagnostic = {"version": 2, "phase": "claim_first_validation", "status": "failed", "workflow_run_id": report_run_id, "source_run_id": source_run, "category": type(exc).__name__}
            if isinstance(exc, ClaimGenerationError) and exc.diagnostics:
                diagnostic["claim_generation"] = exc.diagnostics
            if isinstance(exc, ClaimRenderingError) and exc.diagnostics:
                diagnostic["claim_rendering"] = exc.diagnostics
            context.write_shared("report_generation_diagnostics", diagnostic)
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
        report_id_candidate = str(uuid4())
        system_title = brief.title or "Desk Research Report"
        if self._report_contract_version == EDITORIAL_CONTRACT_VERSION:
            authority_digest = report_claims_authority_digest(claims)
            try:
                catalog = build_authorized_editorial_catalog(
                    claims, citation_registry=registry.to_dict(),
                )
                composition = self._editorial_composer.compose(
                    report_id=report_id_candidate,
                    revision_number=revision,
                    source_report_id=report_id_candidate,
                    authority_digest=authority_digest,
                    catalog=catalog,
                )
                presentation = replace(composition.report, title=system_title)
                editorial_diagnostics = dict(composition.diagnostics)
                editorial_diagnostics.update({
                    "contract_version": EDITORIAL_CONTRACT_VERSION,
                    "authority_digest": authority_digest,
                    "presentation_digest": presentation_report_digest(presentation),
                })
                metadata = attach_editorial_envelope(
                    metadata, presentation=presentation, claims=claims,
                    diagnostics=editorial_diagnostics,
                )
            except (EditorialCompositionError, ValueError) as exc:
                diagnostics = dict(getattr(exc, "diagnostics", {}) or {})
                context.write_shared("report_generation_diagnostics", {
                    "version": 2,
                    "phase": "editorial_composition",
                    "status": "failed",
                    "workflow_run_id": report_run_id,
                    "source_run_id": source_run,
                    "category": type(exc).__name__,
                    "editorial": diagnostics,
                })
                raise ReportError(
                    f"Editorial Report composition failed for run {report_run_id}"
                ) from exc
        report = Report(id=report_id_candidate, project_id=project_id, workflow_run_id=report_run_id, research_design_id=design.id, title=system_title, language=brief.language or design.language or "en", sections=sections, executive_summary=rendered.executive_summary, limitations=limitations, created_at=datetime.now(timezone.utc).isoformat(), generation_method=method, finding_refs=tuple(sorted({ref for claim in claims for ref in claim.finding_ids})), insight_refs=tuple(sorted({ref for claim in claims for ref in claim.insight_ids})), evidence_refs=tuple(sorted({ref for claim in claims for ref in claim.evidence_ids})), citation_registry=registry.to_dict(), deduplication_key=dedup, revision_number=revision, approval_status="draft", metadata=metadata)
        existing = self._report_repository.get_by_deduplication_key(report_run_id, dedup)
        if existing is None:
            try: self._report_claim_repository.create_with_report(report, claims)
            except ReportClaimConflictError as exc:
                context.write_shared("report_generation_diagnostics", {
                    "version": 2,
                    "phase": "atomic_persistence",
                    "status": "failed",
                    "workflow_run_id": report_run_id,
                    "source_run_id": source_run,
                    "category": "atomic_structured_report_persistence_failed",
                    "report_contract_version": self._report_contract_version,
                })
                raise ReportError("Atomic structured Report persistence failed") from exc
            report_id = report.id
        else:
            stored_claims = self._report_claim_repository.list_for_report(existing.id, existing.revision_number)
            if not stored_claims: raise ReportError("Structured Report exists without required ReportClaims")
            report_id = existing.id
        persisted = self._report_repository.get_by_id(report_id)
        if persisted is None: raise ReportError(f"Failed to load persisted report {report_id}")
        if self._report_contract_version == EDITORIAL_CONTRACT_VERSION:
            stored_claims = tuple(
                self._report_claim_repository.list_for_report(
                    persisted.id, persisted.revision_number,
                )
            )
            read_presentation_report(persisted, claims=stored_claims)
            context.write_shared("report_generation_diagnostics", {
                "version": 2,
                "phase": "persisted",
                "status": "completed",
                "workflow_run_id": report_run_id,
                "source_run_id": source_run,
                "report_id": report_id,
                "claim_count": len(claims),
                "report_contract_version": EDITORIAL_CONTRACT_VERSION,
                "editorial": dict(persisted.metadata["editorial"]["diagnostics"]),
            })
            return ReportSummary(
                report_id=report_id, artifact_id="", section_count=len(sections),
                sections_rejected=0, batch_failures=0,
            )
        markdown = render_report_markdown(persisted); checksum = compute_content_checksum(markdown)
        artifact_dedup = compute_artifact_deduplication_key(workflow_run_id=report_run_id, artifact_type=DR06_RESEARCH_REPORT_TYPE)
        artifact_id = self._persist_artifact(artifact=ArtifactRecord(id=str(uuid4()), project_id=project_id, artifact_type="research_report", title=persisted.title, content=markdown, run_id=report_run_id, status="draft", media_type="text/markdown", filename=safe_report_filename(persisted.title), content_checksum=checksum, deduplication_key=artifact_dedup, report_id=report_id), workflow_run_id=report_run_id, deduplication_key=artifact_dedup)
        context.write_shared("report_generation_diagnostics", {"version": 2, "phase": "persisted", "status": "completed", "workflow_run_id": report_run_id, "source_run_id": source_run, "report_id": report_id, "claim_count": len(claims)})
        return ReportSummary(report_id=report_id, artifact_id=artifact_id, section_count=len(sections), sections_rejected=0, batch_failures=0)

    def revise_for_context(self, context: WorkflowContext, *, review_result: ReviewResult) -> ReportSummary:
        current = self._latest_report(context.project.id, context.workflow_run.id)
        if current is None or current.metadata.get("structured_claim_contract") != "desk_report_claim_v1":
            return super().revise_for_context(context, review_result=review_result)
        if review_result.report_id != current.id or review_result.review_attempt != 1:
            raise ReportError("Structured Report revision must target the exact first reviewed revision")
        if any(issue.metadata.get("non_repairable") for issue in review_result.issues):
            raise ReportError("Non-repairable Review issue cannot create a structured revision")
        affected_ids = {issue.report_section_id for issue in review_result.issues if issue.report_section_id}
        affected_claims = {claim_id for issue in review_result.issues for claim_id in issue.claim_refs}
        affected_rqs = {rq for issue in review_result.issues for rq in issue.research_question_refs}
        affected_summary = any(bool(issue.metadata.get("summary_unit_indices")) for issue in review_result.issues)
        for section in current.sections:
            if set(section.claim_refs) & affected_claims:
                affected_ids.add(section.id)
            if set(section.research_question_refs) & affected_rqs:
                affected_ids.add(section.id)
        if not affected_ids and not affected_summary:
            raise ReportError("Structured REVISE issues must target affected Report units")

        old_claims = tuple(self._report_claim_repository.list_for_report(current.id, current.revision_number))
        if not old_claims:
            raise ReportError("Structured Report revision has no persisted ReportClaims")
        report_id = str(uuid4()); next_revision = current.revision_number + 1
        claim_map = {
            claim.claim_id: str(uuid5(NAMESPACE_URL, f"{report_id}:{next_revision}:{claim.claim_id}"))
            for claim in old_claims
        }
        new_claims = tuple(
            ReportClaim.from_dict({**claim.to_dict(), "claim_id": claim_map[claim.claim_id]})
            for claim in old_claims
        )
        design = self._resolve_design(context)
        from application.replay.desk_downstream_replay import source_run_id
        source_run = source_run_id(context)
        findings = self._finding_repository.list_for_project(context.project.id, workflow_run_id=source_run)
        evidence = self._evidence_repository.list_for_project(context.project.id, workflow_run_id=source_run)
        finding_by_id = {item.id: item for item in findings}; evidence_by_id = {item.id: item for item in evidence}
        for claim in new_claims:
            authority = derive_claim_authority(
                project_id=context.project.id, source_workflow_run_id=source_run,
                report_workflow_run_id=context.workflow_run.id, design=design,
                findings=tuple(finding_by_id[item] for item in claim.finding_ids),
                evidence_by_id=evidence_by_id,
            )
            validate_report_claim(claim, authority)

        rerendered = render_validated_claims(claims=new_claims, design=design)
        replacement_by_rq = {
            rq: section for section in rerendered.sections for rq in section.research_question_refs
        }
        revised_sections = []
        for section in current.sections:
            if section.id in affected_ids:
                replacements = [replacement_by_rq[rq] for rq in section.research_question_refs if rq in replacement_by_rq]
                if not replacements:
                    raise ReportError("Affected structured section cannot be rerendered from validated claims")
                revised_sections.extend(replacements)
                continue
            metadata = dict(section.metadata)
            paragraphs = metadata.get("paragraphs")
            if isinstance(paragraphs, list):
                metadata["paragraphs"] = [
                    {**item, "claim_ids": [claim_map.get(value, value) for value in item.get("claim_ids", [])]}
                    if isinstance(item, dict) else item for item in paragraphs
                ]
            revised_sections.append(replace(section, claim_refs=tuple(claim_map[item] for item in section.claim_refs), metadata=metadata))

        metadata = dict(current.metadata)
        metadata.update({"revision_of": current.id, "triggering_review_id": review_result.id})
        metadata["summary_units"] = list(rerendered.summary_units) if affected_summary else [
            {**item, "claim_ids": [claim_map.get(value, value) for value in item.get("claim_ids", [])]}
            for item in metadata.get("summary_units", []) if isinstance(item, dict)
        ]
        dedup = compute_report_deduplication_key(workflow_run_id=context.workflow_run.id, report_type=DR06_RESEARCH_REPORT_TYPE, generation_method=current.generation_method, revision_number=next_revision)
        revised = replace(
            current, id=report_id, sections=tuple(revised_sections), metadata=metadata,
            executive_summary=(rerendered.executive_summary if affected_summary else current.executive_summary),
            created_at=datetime.now(timezone.utc).isoformat(), revision_number=next_revision,
            previous_report_id=current.id, approval_status="draft", deduplication_key=dedup, version=0,
        )
        contract = resolve_report_coverage_contract(report=revised, design=design)
        mandatory = {
            rq: tuple(sorted(item.id for item in findings if rq in item.research_question_refs))
            for rq in contract.required_rq_ids
        }
        coverage_errors = validate_claim_backed_coverage(
            claims=new_claims, sections=revised.sections, contract=contract,
            mandatory_rq_findings=mandatory,
        )
        if coverage_errors:
            raise ReportError(f"Structured revision coverage failed: {list(coverage_errors)}")
        self._report_claim_repository.create_with_report(revised, new_claims)
        artifact_dedup = compute_artifact_deduplication_key(workflow_run_id=context.workflow_run.id, artifact_type=DR06_RESEARCH_REPORT_TYPE)
        existing_artifact = self._artifact_repository.get_by_deduplication_key(context.workflow_run.id, artifact_dedup)
        if existing_artifact is None:
            raise ReportError("No draft artifact to revise for structured Report")
        markdown = render_report_markdown(revised)
        updated = replace(existing_artifact, title=revised.title, content=markdown, filename=safe_report_filename(revised.title), content_checksum=compute_content_checksum(markdown), report_id=revised.id)
        self._artifact_repository.save(updated, expected_version=existing_artifact.version)
        return ReportSummary(report_id=revised.id, artifact_id=existing_artifact.id, section_count=len(revised.sections), sections_rejected=0, batch_failures=0)
