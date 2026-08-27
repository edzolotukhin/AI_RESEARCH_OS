from __future__ import annotations

from dataclasses import asdict, replace
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.research_design_authority import RequirementObligation
from domain.quantitative.research_question_coverage import (
    RH_METHOD_VERSION,
    AnalyticalRequirementEvidenceAssessment,
    ApprovedResearchQuestionCoverageProjection,
    DatasetOnlyResearchQuestionCoverageAbsence,
    QuantitativeResearchQuestionCoverageApproval,
    QuantitativeResearchQuestionCoverageAssessmentVersion,
    QuantitativeResearchQuestionCoverageRunManifest,
    QuantitativeAuthorityReference,
    RequirementExecutionBranchReference,
    ResearchQuestionAssessmentStatus,
    ResearchQuestionCoverageDecision,
    ResearchQuestionCoverageLifecycle,
)


class QuantitativeResearchQuestionCoverageError(ValueError):
    pass


class QuantitativeResearchQuestionCoverageService:
    """Provider-free aggregation of the immutable QZ..RG authority chain."""

    def __init__(self, *, repository, digest_provider, state_service=None, analysis_plan_service=None, analysis_execution_repository=None, finding_lineage_repository=None, insight_lineage_repository=None, report_lineage_repository=None, current_authority_resolver=None):
        self.repository = repository
        self._digest = digest_provider
        self._state = state_service
        self._plans = analysis_plan_service
        self._execution = analysis_execution_repository
        self._findings = finding_lineage_repository
        self._insights = insight_lineage_repository
        self._reports = report_lineage_repository
        self._current_authority_resolver = current_authority_resolver

    def assess_current(self, *, project_id, run_id, state, plan, created_at="WORKFLOW", created_by="SYSTEM"):
        if any(x is None for x in (self._state, self._plans, self._execution, self._findings)):
            raise QuantitativeResearchQuestionCoverageError("RH production authority composition is unavailable")
        design = self._plans._designs.resolve_current_approved(project_id=project_id, run_id=run_id)
        questionnaire = self._plans._questionnaires.resolve_current_approved(project_id=project_id, run_id=run_id)
        ra = self._plans._questionnaires.derive_coverage_manifest(questionnaire.version_id, project_id=project_id)
        reconciliation = self._plans._reconciliations._repository.get_reconciliation(plan.reconciliation_version_id, project_id=project_id)
        rb = self._plans._reconciliations._repository.get_availability(reconciliation.data_availability_manifest_id, project_id=project_id)
        rc = self._plans._repository.get_coverage(plan.coverage_manifest_id, project_id=project_id)
        rd = self._execution.get_manifest(state.get("analysis_execution_manifest_record_id", ""), project_id=project_id)
        rd_coverage = self._execution.get_coverage(rd.coverage_manifest_id, project_id=project_id) if rd else None
        re = self._findings.get_coverage(state.get("finding_coverage_manifest_record_id", ""), project_id=project_id)
        rf = self._insights.get_coverage(state.get("insight_coverage_manifest_record_id", ""), project_id=project_id) if self._insights and state.get("insight_coverage_manifest_record_id") else None
        rg = self._reports.get_coverage(state.get("report_coverage_manifest_record_id", ""), project_id=project_id) if self._reports and state.get("report_coverage_manifest_record_id") else None
        re_lineage = self._findings.get_manifest(state.get("finding_lineage_manifest_record_id", ""), project_id=project_id) if state.get("finding_lineage_manifest_record_id") else None
        rf_lineage = self._insights.get_manifest(state.get("insight_lineage_manifest_record_id", ""), project_id=project_id) if self._insights and state.get("insight_lineage_manifest_record_id") else None
        rg_lineage = self._reports.get_manifest(state.get("report_lineage_manifest_record_id", ""), project_id=project_id) if self._reports and state.get("report_lineage_manifest_record_id") else None
        if any(x is None for x in (ra, rb, rc, rd, rd_coverage, re)):
            raise QuantitativeResearchQuestionCoverageError("mandatory QZ-RG authority is unavailable")
        assessments = self.assess(project_id=project_id, run_id=run_id, design=design,
            questionnaire_coverage=ra, data_availability=rb, plan=plan,
            plan_coverage=rc, execution_manifest=rd, execution_coverage=rd_coverage,
            finding_coverage=re, insight_coverage=rf, report_coverage=rg,
            finding_lineage=re_lineage, insight_lineage=rf_lineage, report_lineage=rg_lineage,
            created_at=created_at, created_by=created_by)
        entries = tuple((item.version_id, item.fingerprint) for item in assessments)
        fingerprint = canonical_digest({"contract":"RH_RUN_MANIFEST_V1","project":project_id,"run":run_id,"design":design.fingerprint,"assessments":entries,"method":RH_METHOD_VERSION}, digest_provider=self._digest)
        manifest = QuantitativeResearchQuestionCoverageRunManifest(
            str(uuid5(NAMESPACE_URL, f"rh-run:{project_id}:{run_id}:{fingerprint}")),
            project_id, run_id, design.version_id, design.fingerprint, entries,
            "IN_REVIEW", RH_METHOD_VERSION, fingerprint,
        )
        return self.repository.save_run_manifest(manifest)
    def assess(
        self, *, project_id, run_id, design, questionnaire_coverage,
        data_availability, plan, plan_coverage, execution_manifest,
        execution_coverage, finding_coverage, insight_coverage=None,
        report_coverage=None, created_at, created_by,
        non_significant_outcome_ids=(), contradictory_requirement_ids=(), version_sequence=1,
        finding_lineage=None, insight_lineage=None, report_lineage=None,
        parent_version_id=None,
    ):
        self._preflight(
            project_id, run_id, design, questionnaire_coverage,
            data_availability, plan, plan_coverage, execution_manifest,
            execution_coverage, finding_coverage, insight_coverage,
            report_coverage,
        )
        ra = {x.requirement_id: x for x in questionnaire_coverage.requirements}
        rb = {x.requirement_id: x for x in data_availability.requirements}
        rc = {x.requirement_id: x for x in plan_coverage.requirements}
        rd_by_requirement = {}
        for item in execution_coverage.entries:
            for requirement_id in item.analytical_requirement_ids:
                rd_by_requirement.setdefault(requirement_id, []).append(item)
        re = {x.analytical_requirement_id: x for x in finding_coverage.entries}
        rf = {x.analytical_requirement_id: x for x in getattr(insight_coverage, "entries", ())}
        rg = {x.analytical_requirement_id: x for x in getattr(report_coverage, "entries", ())}
        requirements = {x.requirement_id: x for x in design.analytical_requirements}
        upstream = self._upstream(
            questionnaire_coverage, data_availability, plan, plan_coverage,
            execution_manifest, execution_coverage, finding_coverage,
            insight_coverage, report_coverage,
        )
        upstream_references = self._upstream_references(
            design, questionnaire_coverage, data_availability, plan, plan_coverage,
            execution_manifest, execution_coverage, finding_coverage,
            insight_coverage, report_coverage,
        )
        values = []
        for question in sorted(design.research_questions, key=lambda x: x.question_id):
            linked = sorted(
                (item for item in requirements.values() if question.question_id in item.research_question_ids),
                key=lambda x: x.requirement_id,
            )
            entries = tuple(
                self._requirement_entry(
                    item, ra.get(item.requirement_id), rb.get(item.requirement_id),
                    rc.get(item.requirement_id), tuple(rd_by_requirement.get(item.requirement_id, ())),
                    re.get(item.requirement_id), rf.get(item.requirement_id), rg.get(item.requirement_id),
                    set(non_significant_outcome_ids), set(contradictory_requirement_ids),
                    project_id, finding_lineage, insight_lineage, report_lineage,
                )
                for item in linked
            )
            mandatory = tuple(x.requirement_id for x in linked if x.obligation is RequirementObligation.MANDATORY)
            optional = tuple(x.requirement_id for x in linked if x.obligation is RequirementObligation.OPTIONAL)
            status = self._question_status(entries, mandatory)
            blockers = tuple(sorted({reason for item in entries if item.status is ResearchQuestionAssessmentStatus.BLOCKED for reason in item.reason_codes}))
            limitations = tuple(sorted({reason for item in entries for reason in item.limitations}))
            assessment_id = str(uuid5(NAMESPACE_URL, f"rh:{project_id}:{run_id}:{question.question_id}"))
            version_id = str(uuid5(NAMESPACE_URL, f"{assessment_id}:{version_sequence}:{upstream}"))
            payload = {
                "contract": "RH_RQ_ASSESSMENT_V1", "project": project_id, "run": run_id,
                "design": design.fingerprint, "question": question.question_id,
                "statement": question.statement, "objectives": tuple(sorted(question.objective_ids)),
                "mandatory": mandatory, "optional": optional,
                "requirements": tuple(asdict(x) for x in entries), "upstream": upstream,
                "upstream_references": tuple(asdict(x) for x in upstream_references),
                "status": status.value, "blockers": blockers, "limitations": limitations,
                "method": RH_METHOD_VERSION,
            }
            value = QuantitativeResearchQuestionCoverageAssessmentVersion(
                assessment_id, version_id, version_sequence, project_id, run_id,
                "QUANTITATIVE", design.version_id, design.fingerprint,
                question.question_id, question.statement, tuple(sorted(question.objective_ids)),
                mandatory, optional, entries, upstream, status, blockers, limitations,
                RH_METHOD_VERSION, parent_version_id, ResearchQuestionCoverageLifecycle.IN_REVIEW,
                None, canonical_digest(payload, digest_provider=self._digest), created_at, created_by,
                upstream_references,
            )
            values.append(self.repository.save_assessment(value))
        return tuple(values)

    def approve(self, version_id, *, project_id, run_id, new_version_id, approval_id,
                expected_fingerprint, decision, actor_id, decided_at, rationale):
        value = self.repository.get_assessment(version_id, project_id=project_id)
        if value is None or value.run_id != run_id:
            raise QuantitativeResearchQuestionCoverageError("ResearchQuestion assessment is unavailable for project/run")
        if value.lifecycle_status is not ResearchQuestionCoverageLifecycle.IN_REVIEW or value.fingerprint != expected_fingerprint:
            raise QuantitativeResearchQuestionCoverageError("assessment approval fingerprint is stale")
        if value.status is ResearchQuestionAssessmentStatus.BLOCKED:
            raise QuantitativeResearchQuestionCoverageError("blocked assessment cannot be approved")
        decision = ResearchQuestionCoverageDecision(decision)
        if decision is ResearchQuestionCoverageDecision.SUFFICIENTLY_ANSWERED and value.status not in {
            ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW,
            ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW,
        }:
            raise QuantitativeResearchQuestionCoverageError("insufficient structural evidence cannot be approved as answered")
        if decision is ResearchQuestionCoverageDecision.NOT_APPLICABLE and value.status is not ResearchQuestionAssessmentStatus.NOT_APPLICABLE:
            raise QuantitativeResearchQuestionCoverageError("NOT_APPLICABLE requires structural authority")
        rationale = " ".join(rationale.split())
        if not rationale:
            raise QuantitativeResearchQuestionCoverageError("approval rationale is required")
        payload = {
            "contract": "RH_RQ_APPROVAL_V1", "project": project_id, "run": run_id,
            "assessment": value.fingerprint, "upstream": value.upstream_authority_fingerprints,
            "upstream_references": tuple(asdict(x) for x in value.upstream_authority_references),
            "decision": decision.value, "actor": actor_id, "time": decided_at,
            "rationale": rationale,
        }
        approved = replace(
            value, version_id=new_version_id, version_sequence=value.version_sequence + 1,
            parent_version_id=value.version_id,
            lifecycle_status=ResearchQuestionCoverageLifecycle.APPROVED,
            approval_reference=approval_id, created_at=decided_at, created_by=actor_id,
        )
        approval = QuantitativeResearchQuestionCoverageApproval(
            approval_id, project_id, run_id, approved.version_id, approved.fingerprint,
            value.upstream_authority_fingerprints, decision, actor_id, decided_at,
            rationale, canonical_digest(payload, digest_provider=self._digest),
            value.upstream_authority_references,
        )
        self.repository.save_approval(approval)
        self.repository.save_assessment(approved)
        return approved

    def reject(self, version_id, *, project_id, run_id, new_version_id, actor_id, decided_at):
        value = self.repository.get_assessment(version_id, project_id=project_id)
        if value is None or value.run_id != run_id or value.lifecycle_status is not ResearchQuestionCoverageLifecycle.IN_REVIEW:
            raise QuantitativeResearchQuestionCoverageError("assessment is unavailable for rejection")
        rejected = replace(value, version_id=new_version_id, version_sequence=value.version_sequence + 1,
            parent_version_id=value.version_id, lifecycle_status=ResearchQuestionCoverageLifecycle.REJECTED,
            created_at=decided_at, created_by=actor_id)
        return self.repository.save_assessment(rejected)

    def supersede(self, version_id, *, project_id, run_id, new_version_id, actor_id, changed_at):
        value = self.repository.get_assessment(version_id, project_id=project_id)
        if value is None or value.run_id != run_id or value.lifecycle_status is not ResearchQuestionCoverageLifecycle.APPROVED:
            raise QuantitativeResearchQuestionCoverageError("only approved assessment can be superseded")
        superseded = replace(value, version_id=new_version_id, version_sequence=value.version_sequence + 1,
            parent_version_id=value.version_id, lifecycle_status=ResearchQuestionCoverageLifecycle.SUPERSEDED,
            approval_reference=None, created_at=changed_at, created_by=actor_id)
        return self.repository.save_assessment(superseded)
    def resolve_current_approved(self, *, project_id, run_id, research_question_id, upstream_authority_fingerprints=None):
        matches = tuple(x for x in self.repository.list_assessments(project_id=project_id, run_id=run_id) if x.research_question_id == research_question_id)
        if not matches:
            raise QuantitativeResearchQuestionCoverageError("no ResearchQuestion coverage assessment")
        value = matches[-1]
        if self._current_authority_resolver is not None:
            current = tuple(self._current_authority_resolver(project_id=project_id, run_id=run_id))
            if not value.upstream_authority_references or value.upstream_authority_references != current:
                raise QuantitativeResearchQuestionCoverageError("ResearchQuestion coverage authority is stale or unapproved")
        elif upstream_authority_fingerprints is None:
            raise QuantitativeResearchQuestionCoverageError("independent RH current-authority resolver is unavailable")
        elif value.upstream_authority_fingerprints != tuple(upstream_authority_fingerprints):
            raise QuantitativeResearchQuestionCoverageError("ResearchQuestion coverage authority is stale or unapproved")
        if value.lifecycle_status is not ResearchQuestionCoverageLifecycle.APPROVED:
            raise QuantitativeResearchQuestionCoverageError("ResearchQuestion coverage authority is stale or unapproved")
        approval = self.repository.get_approval(value.approval_reference or "", project_id=project_id)
        if approval is None or approval.assessment_fingerprint != value.fingerprint or approval.upstream_authority_fingerprints != value.upstream_authority_fingerprints or approval.upstream_authority_references != value.upstream_authority_references:
            raise QuantitativeResearchQuestionCoverageError("ResearchQuestion coverage approval is missing or stale")
        return ApprovedResearchQuestionCoverageProjection(
            value.assessment_id, value.version_id, value.fingerprint,
            value.research_question_id, value.objective_ids, approval.decision,
            tuple((x.analytical_requirement_id, x.status.value) for x in value.requirement_assessments),
            value.blockers, value.limitations, approval.approval_id, approval.fingerprint,
            value.research_design_version_id, value.research_design_fingerprint,
            value.mandatory_requirement_ids, value.optional_requirement_ids,
            value.upstream_authority_fingerprints, value.upstream_authority_references,
        )

    def dataset_only_absence(self, *, project_id, run_id):
        status = "NO_DESIGN_AWARE_RQ_COVERAGE"
        limitation = "ResearchQuestion evidence sufficiency cannot be assessed without approved design-aware authority."
        absence_id = str(uuid5(NAMESPACE_URL, f"rh-absence:{project_id}:{run_id}"))
        value = DatasetOnlyResearchQuestionCoverageAbsence(
            absence_id, project_id, run_id, status, limitation,
            canonical_digest({"contract": "RH_DATASET_ONLY_V1", "id": absence_id, "status": status}, digest_provider=self._digest),
        )
        return self.repository.save_dataset_only_absence(value)

    def _requirement_entry(self, requirement, ra, rb, rc, rd, re, rf, rg, non_significant, contradictory,
                           project_id, finding_lineage, insight_lineage, report_lineage):
        reasons = []
        status = ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW
        ra_status = getattr(getattr(ra, "status", None), "value", "MISSING")
        rb_status = getattr(getattr(rb, "status", None), "value", "MISSING")
        rc_status = getattr(getattr(rc, "status", None), "value", "MISSING")
        re_status = getattr(getattr(re, "status", None), "value", "MISSING")
        rd_values = tuple(sorted((x.planned_item_id, x.outcome_id or "", x.status.value) for x in rd))
        blocking_ra = {"NOT_MEASURED", "MISSING"}
        blocking_rb = {"MISSING_IN_DATA", "INCOMPATIBLE_IN_DATA", "TRANSFORMATION_REQUIRED", "MISSING"}
        blocking_rc = {"NOT_PLANNED", "BLOCKED_BY_MEASUREMENT", "TRANSFORMATION_REQUIRED", "NOT_ANALYZABLE_UNSUPPORTED_METHOD", "MISSING"}
        blocking_rd = {"FAILED_EXECUTION", "BLOCKED_STALE_AUTHORITY", "BLOCKED_PRECURSOR"}
        if ra_status in blocking_ra: reasons.append("MEASUREMENT_NOT_DESIGNED")
        if rb_status in blocking_rb: reasons.append("MEASUREMENT_NOT_AVAILABLE")
        if rc_status in blocking_rc: reasons.append("ANALYSIS_NOT_EXECUTABLE")
        if not rd_values or any(x[2] in blocking_rd for x in rd_values): reasons.append("MANDATORY_EXECUTION_UNAVAILABLE")
        if requirement.obligation is RequirementObligation.MANDATORY and reasons:
            status = ResearchQuestionAssessmentStatus.BLOCKED
        elif any(x[2] == "EXECUTED_NO_VALID_RESULT" for x in rd_values):
            status = ResearchQuestionAssessmentStatus.INCONCLUSIVE
        elif requirement.requirement_id in contradictory or any(x[1] in non_significant for x in rd_values):
            status = ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW
            reasons.append("METHODOLOGICAL_INTERPRETATION_REQUIRED")
        elif re_status == "FINDING_SUPPORTED":
            status = ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW
        elif re_status == "PROPOSALS_REJECTED_UNSUPPORTED":
            status = ResearchQuestionAssessmentStatus.INCONCLUSIVE
            reasons.append("FINDING_PROPOSALS_REJECTED")
        elif re_status in {"NO_FINDING_PROPOSED", "MISSING"}:
            status = ResearchQuestionAssessmentStatus.NOT_ANSWERED
            reasons.append("NO_SUPPORTED_FINDING")
        elif re_status == "NOT_APPLICABLE":
            status = ResearchQuestionAssessmentStatus.NOT_APPLICABLE
        elif requirement.obligation is RequirementObligation.OPTIONAL and reasons:
            status = ResearchQuestionAssessmentStatus.NOT_ANSWERED
        else:
            status = ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW
        branches = self._branch_references(requirement.requirement_id, rd, project_id,
            finding_lineage, insight_lineage, report_lineage)
        payload = {
            "contract": "RH_REQUIREMENT_V1", "id": requirement.requirement_id,
            "obligation": requirement.obligation.value, "ra": ra_status, "rb": rb_status,
            "rc": rc_status, "rd": rd_values, "re": re_status,
            "findings": tuple(getattr(re, "finding_ids", ())),
            "rf": getattr(getattr(rf, "status", None), "value", None),
            "insights": tuple(getattr(rf, "insight_ids", ())),
            "rg": getattr(getattr(rg, "status", None), "value", None),
            "sections": tuple(getattr(rg, "section_ids", ())),
            "status": status.value, "reasons": tuple(sorted(set(reasons))),
            "branches": tuple(asdict(x) for x in branches),
        }
        return AnalyticalRequirementEvidenceAssessment(
            requirement.requirement_id, requirement.obligation.value, ra_status, rb_status,
            rc_status, rd_values, re_status, tuple(getattr(re, "finding_ids", ())),
            getattr(getattr(rf, "status", None), "value", None), tuple(getattr(rf, "insight_ids", ())),
            getattr(getattr(rg, "status", None), "value", None), tuple(getattr(rg, "section_ids", ())),
            status, tuple(sorted(set(reasons))), (), canonical_digest(payload, digest_provider=self._digest), branches,
        )

    def _branch_references(self, requirement_id, rd_entries, project_id, re_manifest, rf_manifest, rg_manifest):
        re_entries = tuple(x for x in getattr(re_manifest, "entries", ()) if requirement_id in x.analytical_requirement_ids)
        rf_entries = tuple(x for x in getattr(rf_manifest, "entries", ()) if requirement_id in x.common_analytical_requirement_ids)
        rg_entries = tuple(x for x in getattr(rg_manifest, "entries", ()) if requirement_id in x.common_analytical_requirement_ids)
        values = []
        for item in rd_entries:
            item_kind = getattr(item, "item_kind", "ANALYSIS")
            outcome = None
            if self._execution is not None and item.outcome_id:
                getter = self._execution.get_comparison_outcome if item_kind == "COMPARISON" else self._execution.get_analysis_outcome
                outcome = getter(item.outcome_id, project_id=project_id)
            values.append(RequirementExecutionBranchReference(
                item.planned_item_id, item_kind, item.outcome_id or "",
                getattr(outcome, "fingerprint", ""),
                tuple(sorted((x.finding_id, x.qh_validation_fingerprint) for x in re_entries)),
                tuple(sorted(x.fingerprint for x in re_entries)),
                tuple(sorted((x.insight_id, x.qj_validation_fingerprint) for x in rf_entries)),
                tuple(sorted(x.fingerprint for x in rf_entries)),
                tuple(sorted((x.section_id, x.fingerprint) for x in rg_entries)),
            ))
        return tuple(values)

    @staticmethod
    def _question_status(entries, mandatory_ids):
        required = tuple(x for x in entries if x.analytical_requirement_id in mandatory_ids)
        considered = required or entries
        if not considered:
            return ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW
        statuses = {x.status for x in considered}
        if ResearchQuestionAssessmentStatus.BLOCKED in statuses:
            return ResearchQuestionAssessmentStatus.BLOCKED
        if statuses == {ResearchQuestionAssessmentStatus.NOT_APPLICABLE}:
            return ResearchQuestionAssessmentStatus.NOT_APPLICABLE
        if statuses == {ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW}:
            return ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW
        if statuses == {ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW}:
            return ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW
        if statuses <= {ResearchQuestionAssessmentStatus.INCONCLUSIVE}:
            return ResearchQuestionAssessmentStatus.INCONCLUSIVE
        if statuses <= {ResearchQuestionAssessmentStatus.NOT_ANSWERED}:
            return ResearchQuestionAssessmentStatus.NOT_ANSWERED
        return ResearchQuestionAssessmentStatus.PARTIALLY_SUPPORTED

    @staticmethod
    def _upstream(ra, rb, plan, rc, rd, rd_coverage, re, rf, rg):
        values = [
            ("ra", ra.fingerprint), ("rb", rb.fingerprint), ("rc_plan", plan.fingerprint),
            ("rc_coverage", rc.fingerprint), ("rd", rd.fingerprint),
            ("rd_coverage", rd_coverage.fingerprint), ("re", re.fingerprint),
        ]
        if rf is not None: values.append(("rf", rf.fingerprint))
        if rg is not None: values.append(("rg", rg.fingerprint))
        return tuple(values)

    @staticmethod
    def _upstream_references(design, ra, rb, plan, rc, rd, rd_coverage, re, rf, rg):
        def ref(kind, value, *ids):
            authority_id = next((getattr(value, name, None) for name in ids if getattr(value, name, None)), None)
            if authority_id is None:
                raise QuantitativeResearchQuestionCoverageError(f"{kind} has no exact authority ID")
            return QuantitativeAuthorityReference(kind, authority_id, value.fingerprint)
        values = [
            ref("QZ_DESIGN", design, "version_id"),
            ref("RA_COVERAGE", ra, "manifest_id"),
            ref("RB_AVAILABILITY", rb, "manifest_id"),
            ref("RC_PLAN", plan, "version_id"),
            ref("RC_COVERAGE", rc, "manifest_id"),
            ref("RD_MANIFEST", rd, "manifest_id"),
            ref("RD_COVERAGE", rd_coverage, "coverage_id"),
            ref("RE_COVERAGE", re, "coverage_id"),
        ]
        if rf is not None: values.append(ref("RF_COVERAGE", rf, "coverage_id"))
        if rg is not None: values.append(ref("RG_COVERAGE", rg, "coverage_id"))
        return tuple(values)

    @staticmethod
    def _preflight(project_id, run_id, design, ra, rb, plan, rc, rd, rd_coverage, re, rf, rg):
        values = (design, ra, rb, plan, rc, rd, rd_coverage, re) + tuple(x for x in (rf, rg) if x is not None)
        if any(getattr(x, "project_id", None) != project_id for x in values):
            raise QuantitativeResearchQuestionCoverageError("wrong-project RH authority")
        if any(getattr(x, "run_id", run_id) != run_id for x in values):
            raise QuantitativeResearchQuestionCoverageError("wrong-run RH authority")
        if plan.research_design_version_id != design.version_id or plan.research_design_fingerprint != design.fingerprint:
            raise QuantitativeResearchQuestionCoverageError("stale QZ/RC authority")
        if ra.research_design_version_id != design.version_id or ra.research_design_fingerprint != design.fingerprint:
            raise QuantitativeResearchQuestionCoverageError("stale QZ/RA authority")
        if rb.reconciliation_fingerprint != plan.reconciliation_fingerprint:
            raise QuantitativeResearchQuestionCoverageError("stale RB/RC authority")
        if rc.plan_version_id != plan.version_id or plan.coverage_manifest_id != rc.manifest_id or plan.coverage_manifest_fingerprint != rc.fingerprint:
            raise QuantitativeResearchQuestionCoverageError("stale RC coverage")
        if rd.plan_version_id != plan.version_id or rd.plan_fingerprint != plan.fingerprint or rd.execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeResearchQuestionCoverageError("stale or non-design-aware RD authority")
        if rd.coverage_manifest_id != rd_coverage.coverage_id or rd.coverage_manifest_fingerprint != rd_coverage.fingerprint:
            raise QuantitativeResearchQuestionCoverageError("stale RD coverage")
