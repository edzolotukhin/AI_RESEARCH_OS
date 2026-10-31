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
from application.report.h3_claim_generation import (
    H3CoverageOutcome, H3ReportInsufficientCoverage, H3ReportTechnicalError,
    generate_h3_structural_claims, restore_h3_claim_structure,
)
from application.report.h3_coverage_plan import build_h3_coverage_plan
from application.report.h3_editorial_delivery import (
    H3PresentationEnvelope, build_h3_editorial_catalog, compose_h3_editorial,
    deterministic_h3_pre_review,
)
from application.report.h3_provider_contract import budget_for_context, h3_provider_budget
from application.report.claim_contract import canonical_digest
from application.report.typed_rendering import H3_CONTRACT_VERSION
from application.report.coverage_contract import CONTRACT_KEY, build_report_coverage_contract, excluded_rq_limitation, resolve_report_coverage_contract
from application.report.deduplication import DR06_RESEARCH_REPORT_TYPE, compute_artifact_deduplication_key, compute_content_checksum, compute_report_deduplication_key
from application.report.exceptions import ReportError
from application.report.markdown_renderer import render_report_markdown, safe_report_filename
from application.report.editorial_composer import EditorialComposer, EditorialCompositionError
from application.report.editorial_contract import (
    EDITORIAL_CONTRACT_VERSION, CoverageLimitation, CoverageStatus,
    ImpactLabel, MissingDimension, build_authorized_editorial_catalog,
)
from application.report.presentation_persistence import (
    attach_editorial_envelope,
    presentation_report_digest,
    presentation_report_to_dict,
    read_presentation_report,
    report_claims_authority_digest,
)
from application.report.report_service import ReportService, ReportSummary
from application.research_quality.analysis_coverage import coverage_snapshot_from_payload
from application.research_quality.research_readiness_service import SHARED_STATE_KEY
from domain.reports.report import Report
from domain.reports.report_claim import ReportClaim
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from runtime.workflow_context import WorkflowContext


class ClaimFirstReportService(ReportService):
    """New Desk path: authority -> claims -> prose; legacy methods stay readable."""

    def __init__(
        self, *, report_claim_repository: ReportClaimRepository,
        report_contract_version: str = "desk_report_claim_v1",
        editorial_composer: EditorialComposer | None = None,
        h3_editorial_provider=None,
        **kwargs,
    ) -> None:
        report_engine = kwargs.get("report_engine")
        super().__init__(**kwargs)
        if report_contract_version not in {"desk_report_claim_v1", EDITORIAL_CONTRACT_VERSION, H3_CONTRACT_VERSION}:
            raise ValueError("unsupported Report contract version")
        if report_contract_version == EDITORIAL_CONTRACT_VERSION and editorial_composer is None:
            raise ValueError("desk_editorial_v1 requires an EditorialComposer")
        self._report_claim_repository = report_claim_repository
        self._report_contract_version = report_contract_version
        self._editorial_composer = editorial_composer
        self._h3_editorial_provider = h3_editorial_provider
        self._claim_candidate_provider = getattr(
            report_engine, "generate_claim_candidates", None,
        )
        self._claim_correction_provider = getattr(
            report_engine, "repair_claim_candidates", None,
        )
        self._h3_candidate_provider = getattr(
            report_engine, "generate_h3_claim_candidates", None,
        )
        self._h3_correction_provider = getattr(
            report_engine, "repair_h3_claim_candidates", None,
        )

    def write_for_context(self, context: WorkflowContext) -> ReportSummary:
        from application.report.contract_selection import (
            DESK_REPORT_CONTRACT_PIN,
            resolve_pinned_desk_report_contract,
        )
        pinned_contract = resolve_pinned_desk_report_contract(
            {DESK_REPORT_CONTRACT_PIN: context.read_shared(DESK_REPORT_CONTRACT_PIN)},
            fallback=self._report_contract_version,
        )
        if pinned_contract != self._report_contract_version:
            raise ReportError("Desk report contract changed after workflow creation")
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
        if self._report_contract_version == H3_CONTRACT_VERSION:
            return self._write_h3_claim_stage(
                context=context, design=design, brief=brief, findings=tuple(findings),
                insights=tuple(insights), evidence_by_id=evidence_by_id,
                source_to_citation=source_to_citation, contract=contract,
                source_run=source_run, coverage=coverage,
                citation_registry=registry.to_dict(),
            )
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
                    limitations=_coverage_limitations(contract),
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
                metadata["editorial_lifecycle"] = {
                    "claim_generation_calls_reserved": 2,
                    "initial_editorial_calls": int(composition.diagnostics.get("provider_call_count", 0)),
                    "semantic_review_calls": 0,
                    "revision_calls": 0,
                }
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

    def _write_h3_claim_stage(
        self, *, context: WorkflowContext, design, brief, findings, insights,
        evidence_by_id, source_to_citation, contract, source_run: str, coverage,
        citation_registry,
    ) -> ReportSummary:
        report_run_id = context.workflow_run.id
        required_ins = tuple(sorted(
            need.id for need in design.information_needs
            if need.research_question_id in set(contract.required_rq_ids)
        ))
        coverage_plan = build_h3_coverage_plan(
            design=design,
            required_information_need_ids=required_ins,
            findings=findings,
            evidence_by_id=evidence_by_id,
            insights=insights,
        )
        if not callable(self._h3_candidate_provider):
            result = generate_h3_structural_claims(
                project_id=context.project.id, source_workflow_run_id=source_run,
                report_workflow_run_id=report_run_id, design=design,
                findings=(), insights=(), evidence_by_id={}, citation_id_by_source={},
                candidate_provider=lambda _: {"contract_version": H3_CONTRACT_VERSION, "claims": []},
                correction_provider=None,
                required_research_question_ids=contract.required_rq_ids,
                required_information_need_ids=required_ins,
                coverage_plan=coverage_plan,
            )
            result = replace(result, coverage_outcome=H3CoverageOutcome.TECHNICAL_ERROR)
            context.write_shared("report_generation_diagnostics", {
                **result.to_diagnostic_dict(), "phase": "h3_claim_generation",
                "status": "failed", "failure_category": "provider_not_configured",
            })
            raise H3ReportTechnicalError(result)
        with h3_provider_budget(budget_for_context(context)):
            result = generate_h3_structural_claims(
                project_id=context.project.id, source_workflow_run_id=source_run,
                report_workflow_run_id=report_run_id, design=design,
                findings=findings, insights=insights, evidence_by_id=evidence_by_id,
                citation_id_by_source=source_to_citation,
                candidate_provider=self._h3_candidate_provider,
                correction_provider=self._h3_correction_provider,
                required_research_question_ids=contract.required_rq_ids,
                required_information_need_ids=required_ins,
                coverage_plan=coverage_plan,
            )
        diagnostic = {
            **result.to_diagnostic_dict(), "phase": "h3_claim_generation",
            "workflow_run_id": report_run_id, "source_run_id": source_run,
        }
        if result.coverage_outcome is H3CoverageOutcome.TECHNICAL_ERROR:
            context.write_shared("report_generation_diagnostics", {**diagnostic, "status": "failed"})
            raise H3ReportTechnicalError(result)
        if result.coverage_outcome is H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE:
            context.write_shared("report_generation_diagnostics", {**diagnostic, "status": "insufficient_coverage"})
            raise H3ReportInsufficientCoverage(result)

        sections = tuple(
            ReportSection(
                id=f"h3-section-{index}", title=f"Structural claim {index}",
                content=claim.proposition,
                research_question_refs=claim.research_question_ids,
                finding_refs=claim.finding_ids, insight_refs=claim.insight_ids,
                evidence_refs=claim.evidence_ids, citation_ids=claim.citation_ids,
                claim_refs=(claim.claim_id,),
                metadata={
                    "contract_version": H3_CONTRACT_VERSION,
                    "typed_ast_digest": claim.structural_assertion["typed_ast_digest"],
                    "render_digest": claim.structural_assertion["render_digest"],
                },
            )
            for index, claim in enumerate(result.claims, start=1)
        )
        excluded = excluded_rq_limitation(contract)
        controlled = (
            "Some optional structural claims were rejected; required coverage remains satisfied."
            if result.coverage_outcome is H3CoverageOutcome.LIMITED else None
        )
        limitations = tuple(dict.fromkeys([
            *design.limitations,
            *((excluded,) if excluded else ()),
            *((controlled,) if controlled else ()),
        ]))
        revision = 1
        method = "claim-first:h3-structural"
        dedup = compute_report_deduplication_key(
            workflow_run_id=report_run_id, report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=method, revision_number=revision,
        )
        report_id = str(uuid4())
        metadata = {
            CONTRACT_KEY: contract.to_metadata(),
            "report_scope": contract.mode,
            "structured_claim_contract": H3_CONTRACT_VERSION,
            "h3_claim_generation": result.to_diagnostic_dict(),
        }
        if coverage is not None:
            metadata.update(coverage.to_dict())
        report = Report(
            id=report_id, project_id=context.project.id, workflow_run_id=report_run_id,
            research_design_id=design.id, title=brief.title or "Desk Research Report",
            language=brief.language or design.language or "uk",
            sections=sections,
            executive_summary=" ".join(claim.proposition for claim in result.claims),
            limitations=limitations, created_at=datetime.now(timezone.utc).isoformat(),
            generation_method=method,
            finding_refs=tuple(sorted({ref for claim in result.claims for ref in claim.finding_ids})),
            insight_refs=tuple(sorted({ref for claim in result.claims for ref in claim.insight_ids})),
            evidence_refs=tuple(sorted({ref for claim in result.claims for ref in claim.evidence_ids})),
            citation_registry=citation_registry, deduplication_key=dedup, revision_number=revision,
            approval_status="draft", metadata=metadata,
        )
        if self._h3_editorial_provider is not None:
            coverage_digest = canonical_digest(contract.to_metadata())
            try:
                editorial_catalog = build_h3_editorial_catalog(
                    report=report, claims=result.claims,
                    coverage_contract_digest=coverage_digest,
                )
                with h3_provider_budget(budget_for_context(context)):
                    presentation = compose_h3_editorial(
                        report=report, catalog=editorial_catalog,
                        provider=self._h3_editorial_provider,
                    )
                deterministic_h3_pre_review(
                    report=report, claims=result.claims, presentation=presentation,
                    coverage_contract_digest=coverage_digest,
                )
                metadata = dict(report.metadata)
                metadata["h3_presentation"] = presentation.to_dict()
                report = replace(report, metadata=metadata)
            except Exception as exc:
                context.write_shared("report_generation_diagnostics", {
                    **diagnostic, "status": "failed",
                    "failure_category": "h3_editorial_composition",
                    "code": str(getattr(exc, "code", type(exc).__name__))[:96],
                    "field_path": getattr(exc, "field_path", None),
                    "actual_kind": getattr(exc, "actual_kind", None),
                })
                raise H3ReportTechnicalError(replace(result, coverage_outcome=H3CoverageOutcome.TECHNICAL_ERROR)) from exc
        try:
            self._report_claim_repository.create_with_report(report, result.claims)
        except Exception as exc:
            failed = {**diagnostic, "status": "failed", "failure_category": "persistence_error"}
            context.write_shared("report_generation_diagnostics", failed)
            technical = result.__class__(
                result.claims, result.diagnostics, H3CoverageOutcome.TECHNICAL_ERROR,
                result.missing_research_question_ids, result.missing_information_need_ids,
                result.provider_attempt_count, result.repair_count,
            )
            raise H3ReportTechnicalError(technical) from exc
        stored = self._report_repository.get_by_id(report_id)
        if stored is None:
            technical = replace(result, coverage_outcome=H3CoverageOutcome.TECHNICAL_ERROR)
            context.write_shared("report_generation_diagnostics", {
                **diagnostic, "status": "failed", "failure_category": "report_reload_failed",
            })
            raise H3ReportTechnicalError(technical)
        try:
            reloaded = tuple(self._report_claim_repository.list_for_report(report_id, revision))
            if len(reloaded) != len(result.claims):
                raise ValueError("h3_claim_reload_count_mismatch")
            for claim in reloaded:
                restore_h3_claim_structure(claim)
        except Exception as exc:
            technical = replace(result, coverage_outcome=H3CoverageOutcome.TECHNICAL_ERROR)
            context.write_shared("report_generation_diagnostics", {
                **diagnostic, "status": "failed", "failure_category": "structural_reload_failed",
            })
            raise H3ReportTechnicalError(technical) from exc
        context.write_shared("report_generation_diagnostics", {
            **diagnostic, "status": "completed", "report_id": report_id,
        })
        return ReportSummary(
            report_id=report_id, artifact_id="", section_count=len(sections),
            sections_rejected=sum(item.outcome.value != "ACCEPTED" for item in result.diagnostics),
            batch_failures=0,
        )

    def revise_for_context(
        self, context: WorkflowContext, *, review_result: ReviewResult | None = None,
    ) -> ReportSummary:
        if review_result is None:
            payload = context.read_shared("review_1")
            if not isinstance(payload, dict):
                raise ReportError("H3 revision requires persisted review_1")
            try:
                review_result = ReviewResult.from_dict(payload)
            except (KeyError, TypeError, ValueError) as exc:
                raise ReportError("H3 revision review state invalid") from exc
        if self._report_contract_version == H3_CONTRACT_VERSION:
            return self._revise_h3_for_context(context, review_result=review_result)
        current = self._latest_report(context.project.id, context.workflow_run.id)
        if current is not None and current.metadata.get("report_contract_version") == EDITORIAL_CONTRACT_VERSION:
            return self._revise_editorial_for_context(
                context, current=current, review_result=review_result,
            )
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

    def _revise_editorial_for_context(
        self, context: WorkflowContext, *, current: Report, review_result: ReviewResult,
    ) -> ReportSummary:
        if self._editorial_composer is None:
            raise ReportError("Editorial revision requires EditorialComposer")
        if review_result.report_id != current.id or review_result.review_attempt != 1:
            raise ReportError("Editorial revision must target exact first reviewed revision")
        if not review_result.issues:
            raise ReportError("Editorial revision requires bounded Review issues")

        old_claims = tuple(self._report_claim_repository.list_for_report(current.id, current.revision_number))
        if not old_claims:
            raise ReportError("Editorial revision has no persisted ReportClaims")
        previous = read_presentation_report(current, claims=old_claims)
        if previous is None:
            raise ReportError("Editorial revision has no persisted PresentationReport")
        old_authority_digest = report_claims_authority_digest(old_claims)
        report_id = str(uuid4())
        next_revision = current.revision_number + 1
        claim_map = {
            claim.claim_id: str(uuid5(NAMESPACE_URL, f"{report_id}:{next_revision}:{claim.claim_id}"))
            for claim in old_claims
        }
        new_claims = tuple(
            ReportClaim.from_dict({**claim.to_dict(), "claim_id": claim_map[claim.claim_id]})
            for claim in old_claims
        )
        if report_claims_authority_digest(new_claims) != old_authority_digest:
            raise ReportError("Editorial revision changed immutable factual authority")

        design = self._resolve_design(context)
        from application.replay.desk_downstream_replay import source_run_id
        source_run = source_run_id(context)
        findings = self._finding_repository.list_for_project(context.project.id, workflow_run_id=source_run)
        evidence = self._evidence_repository.list_for_project(context.project.id, workflow_run_id=source_run)
        finding_by_id = {item.id: item for item in findings}
        evidence_by_id = {item.id: item for item in evidence}
        for claim in new_claims:
            authority = derive_claim_authority(
                project_id=context.project.id, source_workflow_run_id=source_run,
                report_workflow_run_id=context.workflow_run.id, design=design,
                findings=tuple(finding_by_id[item] for item in claim.finding_ids),
                evidence_by_id=evidence_by_id,
            )
            validate_report_claim(claim, authority)

        allowed_target_types = {
            "REPORT", "EXECUTIVE_SUMMARY", "SECTION", "PARAGRAPH",
            "EDITORIAL_UNIT", "REPORT_CLAIM", "COVERAGE_LIMITATION",
        }
        issue_payload = []
        target_payload = []
        exact_targets = {
            ("REPORT", current.id),
            ("EXECUTIVE_SUMMARY", "executive_summary"),
            *(("SECTION", item.section_id) for item in previous.sections),
            *(("PARAGRAPH", item.paragraph_id) for item in (
                previous.executive_summary.paragraphs
                + tuple(p for section in previous.sections for p in section.paragraphs)
            )),
            *(("EDITORIAL_UNIT", unit_id) for unit_id in (
                previous.executive_summary.unit_ids
                + tuple(unit for section in previous.sections for unit in section.unit_ids)
            )),
            *(("REPORT_CLAIM", item.claim_id) for item in old_claims),
            *(("COVERAGE_LIMITATION", item.limitation_id) for item in previous.limitations),
        }
        for issue in review_result.issues:
            target_type = str(issue.metadata.get("target_type", ""))
            target_ref = str(issue.metadata.get("target_ref", ""))
            if target_type not in allowed_target_types or not target_ref:
                raise ReportError("Editorial revision issue has invalid target")
            if (target_type, target_ref) not in exact_targets:
                raise ReportError("Editorial revision issue targets foreign presentation state")
            if target_type == "REPORT_CLAIM":
                if target_ref not in claim_map:
                    raise ReportError("Editorial revision targets foreign ReportClaim")
                target_ref = claim_map[target_ref]
            issue_payload.append({
                "target_type": target_type,
                "target_ref": target_ref,
                "issue_type": str(issue.metadata.get("semantic_issue_type", issue.issue_type.value)),
                "revision_instruction": issue.suggested_action,
            })
            target_payload.append({"target_type": target_type, "target_ref": target_ref})

        registry = CitationRegistry()
        sources = [
            item for item in self._source_repository.list_for_project(context.project.id)
            if source_run in item.workflow_run_refs
        ]
        sources_by_id = {item.id: item for item in sources}
        for item in evidence:
            registry.register_evidence(item, sources_by_id=sources_by_id)
        try:
            old_catalog = build_authorized_editorial_catalog(
                old_claims, citation_registry=registry.to_dict(),
            )
            new_base_catalog = build_authorized_editorial_catalog(
                new_claims, citation_registry=registry.to_dict(),
            )
            period_map: dict[str, str] = {}
            for old_ref, old_period in old_catalog.periods.items():
                old_fact = old_catalog.facts[old_period.fact_ref]
                mapped_claim = claim_map[old_period.claim_ref]
                matches = [
                    ref for ref, item in new_base_catalog.periods.items()
                    if item.claim_ref == mapped_claim
                    and item.period == old_period.period
                    and new_base_catalog.facts[item.fact_ref].numeric_fact == old_fact.numeric_fact
                ]
                if len(matches) != 1:
                    raise ReportError("Editorial limitation period authority cannot be remapped")
                period_map[old_ref] = matches[0]
            revised_limitations = tuple(
                replace(
                    item,
                    supported_claim_refs=tuple(claim_map[ref] for ref in item.supported_claim_refs),
                    supported_period_refs=tuple(period_map[ref] for ref in item.supported_period_refs),
                )
                for item in previous.limitations
            )
            catalog = build_authorized_editorial_catalog(
                new_claims, citation_registry=registry.to_dict(),
                limitations=revised_limitations,
            )
            composition = self._editorial_composer.compose(
                report_id=report_id, revision_number=next_revision,
                source_report_id=current.id, authority_digest=old_authority_digest,
                catalog=catalog,
                revision_context={
                    "previous_presentation": presentation_report_to_dict(previous),
                    "issues": issue_payload,
                    "allowed_targets": target_payload,
                },
            )
            presentation = replace(composition.report, title=current.title)
        except (EditorialCompositionError, ValueError) as exc:
            raise ReportError("Editorial revision composition failed") from exc
        if presentation.authority_digest != old_authority_digest:
            raise ReportError("Editorial revision presentation changed authority digest")

        claim_id_map = claim_map
        revised_sections = tuple(
            replace(section, claim_refs=tuple(claim_id_map.get(item, item) for item in section.claim_refs))
            for section in current.sections
        )
        metadata = dict(current.metadata)
        metadata["summary_units"] = [
            {
                **item,
                "claim_ids": [claim_map.get(value, value) for value in item.get("claim_ids", [])],
            }
            for item in metadata.get("summary_units", [])
            if isinstance(item, dict)
        ]
        initial_calls = int(
            current.metadata.get("editorial_lifecycle", {}).get(
                "initial_editorial_calls",
                current.metadata.get("editorial", {}).get("diagnostics", {}).get("provider_call_count", 0),
            )
        )
        first_review_calls = int(review_result.metadata.get("semantic_provider_call_count", 0))
        revision_calls = int(composition.diagnostics.get("provider_call_count", 0))
        if revision_calls > 2:
            raise ReportError("Editorial revision provider-call bound exceeded")
        editorial_diagnostics = dict(composition.diagnostics)
        editorial_diagnostics.update({
            "contract_version": EDITORIAL_CONTRACT_VERSION,
            "authority_digest": old_authority_digest,
            "presentation_digest": presentation_report_digest(presentation),
        })
        metadata.update({
            "revision_of": current.id,
            "triggering_review_id": review_result.id,
            "editorial_lifecycle": {
                "initial_editorial_calls": initial_calls,
                "semantic_review_calls": first_review_calls,
                "revision_calls": revision_calls,
            },
        })
        metadata = attach_editorial_envelope(
            metadata, presentation=presentation, claims=new_claims,
            diagnostics=editorial_diagnostics,
        )
        dedup = compute_report_deduplication_key(
            workflow_run_id=context.workflow_run.id,
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=current.generation_method,
            revision_number=next_revision,
        )
        revised = replace(
            current, id=report_id, sections=revised_sections, metadata=metadata,
            created_at=datetime.now(timezone.utc).isoformat(),
            revision_number=next_revision, previous_report_id=current.id,
            approval_status="draft", deduplication_key=dedup, version=0,
        )
        contract = resolve_report_coverage_contract(report=revised, design=design)
        mandatory = {
            rq: tuple(sorted(item.id for item in findings if rq in item.research_question_refs))
            for rq in contract.required_rq_ids
        }
        errors = validate_claim_backed_coverage(
            claims=new_claims, sections=revised.sections, contract=contract,
            mandatory_rq_findings=mandatory,
        )
        if errors:
            raise ReportError(f"Editorial revision coverage failed: {list(errors)}")
        try:
            self._report_claim_repository.create_with_report(revised, new_claims)
        except ReportClaimConflictError as exc:
            raise ReportError("Atomic editorial revision persistence failed") from exc
        persisted = self._report_repository.get_by_id(revised.id)
        if persisted is None:
            raise ReportError("Editorial revision persistence did not return Report")
        stored_claims = tuple(self._report_claim_repository.list_for_report(revised.id, next_revision))
        read_presentation_report(persisted, claims=stored_claims)
        return ReportSummary(
            report_id=revised.id, artifact_id="", section_count=len(revised.sections),
            sections_rejected=0, batch_failures=0,
        )

    def _revise_h3_for_context(
        self, context: WorkflowContext, *, review_result: ReviewResult,
    ) -> dict[str, object]:
        """Create/reload H3 R2 while retaining the immutable R1 claim set."""
        if review_result.verdict.value != "revise" or review_result.review_attempt != 1:
            raise ReportError("H3 revision requires persisted review_1 REVISE")
        if not callable(getattr(self._h3_editorial_provider, "compose", None)):
            raise ReportError("H3 revision provider is not configured")

        reports = self._report_repository.list_for_project(
            context.project.id, workflow_run_id=context.workflow_run.id,
        )
        current = next(
            (item for item in reports if item.id == review_result.report_id), None,
        )
        if current is None or current.revision_number != 1:
            raise ReportError("H3 revision requires exact durable R1")
        old_claims = tuple(self._report_claim_repository.list_for_report(current.id, 1))
        if not old_claims:
            raise ReportError("H3 revision has no durable R1 claims")
        old_authority_digest = report_claims_authority_digest(old_claims)
        design = self._resolve_design(context)
        contract = resolve_report_coverage_contract(report=current, design=design)
        coverage_digest = canonical_digest(contract.to_metadata())
        dedup = compute_report_deduplication_key(
            workflow_run_id=context.workflow_run.id,
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=current.generation_method,
            revision_number=2,
        )
        report_id = str(uuid5(
            NAMESPACE_URL,
            f"h3-revision:{context.workflow_run.id}:{current.id}:2",
        ))

        existing = self._report_repository.get_by_deduplication_key(
            context.workflow_run.id, dedup,
        )
        if existing is not None:
            if (
                existing.revision_number != 2
                or existing.previous_report_id != current.id
                or existing.id != report_id
                or existing.project_id != current.project_id
                or existing.workflow_run_id != current.workflow_run_id
                or existing.research_design_id != current.research_design_id
            ):
                raise ReportError("H3 revision identity conflict")
            revised = existing
        else:
            revised = replace(
                current,
                id=report_id,
                revision_number=2,
                previous_report_id=current.id,
                deduplication_key=dedup,
                approval_status="draft",
                version=0,
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata={
                    **current.metadata,
                    "revision_of": current.id,
                    "triggering_review_id": review_result.id,
                    "h3_revision": {"status": "composing", "revision_count": 1},
                },
            )
            catalog = build_h3_editorial_catalog(
                report=revised, claims=old_claims,
                coverage_contract_digest=coverage_digest,
            )
            with h3_provider_budget(budget_for_context(context)):
                presentation = compose_h3_editorial(
                    report=revised, catalog=catalog,
                    provider=self._h3_editorial_provider, revision_number=2,
                )
            deterministic_h3_pre_review(
                report=revised, claims=old_claims, presentation=presentation,
                coverage_contract_digest=coverage_digest,
            )
            revised = replace(
                revised,
                metadata={
                    **revised.metadata,
                    "h3_presentation": presentation.to_dict(),
                    "h3_revision": {
                        "status": "completed", "revision_count": 1,
                        "claim_set_digest": presentation.claim_set_digest,
                        "authority_digest": old_authority_digest,
                        "presentation_digest": presentation.presentation_digest,
                    },
                },
            )
            self._report_repository.create(revised)

        self._report_claim_repository.attach_claims_to_report_revision(
            revised, old_claims,
        )
        stored = self._report_repository.get_by_id(revised.id)
        stored_claims = tuple(
            self._report_claim_repository.list_for_report(revised.id, 2)
        )
        if stored is None or {item.claim_id for item in stored_claims} != {
            item.claim_id for item in old_claims
        }:
            raise ReportError("H3 revision claim membership mismatch")
        if report_claims_authority_digest(stored_claims) != old_authority_digest:
            raise ReportError("H3 revision authority digest mismatch")
        presentation_payload = stored.metadata.get("h3_presentation")
        if not isinstance(presentation_payload, dict):
            raise ReportError("H3 revision presentation missing after persistence")
        presentation = H3PresentationEnvelope.from_dict(presentation_payload)
        deterministic_h3_pre_review(
            report=stored, claims=stored_claims, presentation=presentation,
            coverage_contract_digest=presentation.coverage_contract_digest,
        )
        return {
            "report_id": stored.id,
            "revision_number": 2,
            "previous_report_id": current.id,
            "revision_count": 1,
            "claim_ids": sorted(item.claim_id for item in stored_claims),
            "authority_digest": report_claims_authority_digest(stored_claims),
            "presentation_digest": presentation.presentation_digest,
            "claim_set_digest": presentation.claim_set_digest,
        }


def _coverage_limitations(contract) -> tuple[CoverageLimitation, ...]:
    if contract.mode != "limited":
        return ()
    return tuple(
        CoverageLimitation(
            limitation_id=f"coverage:{rq_id}", topic_ref=rq_id,
            supported_claim_refs=(), supported_period_refs=(),
            missing_dimensions=(MissingDimension.OTHER_BOUNDED,),
            missing_periods=(), coverage_status=CoverageStatus.UNSUPPORTED,
            impact_label=ImpactLabel.REQUIRES_CAUTION,
            evidence_requirement_labels=(),
        )
        for rq_id in contract.excluded_rq_ids
    )
