from __future__ import annotations

from application.quantitative.fingerprints import canonical_digest
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import QuantitativeSupportStatus
from domain.quantitative.insight import QuantitativeInsightValidationStatus
from domain.quantitative.report_lineage import (
    REPORT_COMPOSITION_CONTRACT_VERSION,
    REPORT_LINEAGE_METHOD_VERSION,
    DatasetOnlyReportLineageAbsence,
    DesignAwareReportAbsenceReason,
    DesignAwareReportControlledAbsence,
    DesignAwareReportFindingSupportEntry,
    DesignAwareReportInputAuthority,
    DesignAwareReportInsightSupportEntry,
    QuantitativeReportCoverageManifest,
    QuantitativeReportDesignLineageManifest,
    ReportCoverageEntry,
    ReportCoverageStatus,
    ReportSectionDesignLineageEntry,
    ReportSectionEffectiveSupportBranch,
)


class QuantitativeReportLineageError(QuantitativeAnalysisError):
    pass


class QuantitativeReportLineageService:
    def __init__(self, *, repository, digest_provider) -> None:
        self.repository = repository
        self.digest = digest_provider

    def build_input_authority(
        self, *, project_id, run_id, finding_generation_record_id, findings,
        insight_generation_record_id, insights, re_input, re_manifest,
        re_coverage, rf_input, rf_manifest, rf_coverage,
        deliverable_constraints=(),
    ):
        self._preflight(
            project_id, run_id, finding_generation_record_id, findings,
            insight_generation_record_id, insights, re_input, re_manifest,
            re_coverage, rf_input, rf_manifest, rf_coverage,
        )
        re_entries = {item.finding_id: item for item in re_manifest.entries}
        rf_finding_entries = {item.finding_id: item for item in rf_input.finding_entries}
        rf_entries = {item.insight_id: item for item in rf_manifest.entries}
        if any(len(values) != len(set(values)) for values in (
            tuple(item.finding_id for item in re_manifest.entries),
            tuple(item.finding_id for item in rf_input.finding_entries),
            tuple(item.insight_id for item in rf_manifest.entries),
        )):
            raise QuantitativeReportLineageError("duplicate RE/RF lineage authority")

        finding_entries = []
        for finding in findings.accepted_findings:
            re_entry = re_entries.get(finding.finding_id)
            rf_entry = rf_finding_entries.get(finding.finding_id)
            if (
                finding.support_validation_status is not QuantitativeSupportStatus.SUPPORTED
                or not finding.support_validation_fingerprint
                or re_entry is None
                or rf_entry is None
                or re_entry.qh_validation_fingerprint != finding.support_validation_fingerprint
                or rf_entry.qh_validation_fingerprint != finding.support_validation_fingerprint
                or rf_entry.re_lineage_entry_fingerprint != re_entry.fingerprint
            ):
                raise QuantitativeReportLineageError("accepted Finding lacks exact RE/RF authority")
            payload = {
                "finding": (finding.finding_id, finding.support_validation_fingerprint),
                "re": re_entry.fingerprint,
                "branches": tuple(self._branch_payload(item) for item in rf_entry.branches),
                "version": REPORT_LINEAGE_METHOD_VERSION,
            }
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            finding_entries.append(DesignAwareReportFindingSupportEntry(
                finding.finding_id,
                finding.support_validation_fingerprint,
                self._finding_projection(finding),
                re_entry.fingerprint,
                rf_entry.branches,
                rf_entry.limitations,
                fingerprint,
            ))

        insight_entries = []
        for insight in insights.accepted_insights:
            rf_entry = rf_entries.get(insight.insight_id)
            if (
                insight.validation_status is not QuantitativeInsightValidationStatus.SUPPORTED
                or not insight.validation_fingerprint
                or rf_entry is None
                or rf_entry.qj_validation_fingerprint != insight.validation_fingerprint
                or tuple(ref.finding_id for ref in insight.supporting_finding_refs)
                != rf_entry.supporting_finding_ids
            ):
                raise QuantitativeReportLineageError("accepted Insight lacks exact RF authority")
            payload = {
                "insight": (insight.insight_id, insight.validation_fingerprint),
                "rf": rf_entry.fingerprint,
                "branches": tuple(
                    (finding_id, tuple(self._branch_payload(branch) for branch in branches))
                    for finding_id, branches in rf_entry.branches_by_finding
                ),
                "scope": (
                    rf_entry.common_analytical_requirement_ids,
                    rf_entry.common_research_question_ids,
                    rf_entry.common_scope_objective_ids,
                ),
                "version": REPORT_LINEAGE_METHOD_VERSION,
            }
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            insight_entries.append(DesignAwareReportInsightSupportEntry(
                insight.insight_id,
                insight.validation_fingerprint,
                self._insight_projection(insight),
                rf_entry.fingerprint,
                rf_entry.supporting_finding_ids,
                rf_entry.branches_by_finding,
                rf_entry.common_analytical_requirement_ids,
                rf_entry.common_research_question_ids,
                rf_entry.common_scope_objective_ids,
                rf_input.limitations,
                fingerprint,
            ))

        finding_entries = tuple(sorted(finding_entries, key=lambda item: item.finding_id))
        insight_entries = tuple(sorted(insight_entries, key=lambda item: item.insight_id))
        limitations = tuple(dict.fromkeys(re_input.limitations + rf_input.limitations))
        constraints = tuple(sorted(deliverable_constraints))
        payload = {
            "project": project_id,
            "run": run_id,
            "findings": (finding_generation_record_id, findings.generation_fingerprint),
            "insights": (insight_generation_record_id, insights.generation_fingerprint),
            "re": ((re_input.authority_id, re_input.fingerprint), (re_manifest.manifest_id, re_manifest.fingerprint), (re_coverage.coverage_id, re_coverage.fingerprint)),
            "rf": ((rf_input.authority_id, rf_input.fingerprint), (rf_manifest.manifest_id, rf_manifest.fingerprint), (rf_coverage.coverage_id, rf_coverage.fingerprint)),
            "rd": (re_input.rd_execution_manifest_id, re_input.rd_execution_manifest_fingerprint),
            "rc": (re_input.rc_plan_id, re_input.rc_plan_version_id, re_input.rc_plan_fingerprint),
            "dataset": (re_input.dataset_version_id, re_input.dataset_fingerprint),
            "codebook": (re_input.codebook_version_id, re_input.codebook_fingerprint),
            "finding_entries": tuple(item.fingerprint for item in finding_entries),
            "insight_entries": tuple(item.fingerprint for item in insight_entries),
            "requirements": re_input.analytical_requirement_ids,
            "constraints": constraints,
            "limitations": limitations,
            "contract": REPORT_COMPOSITION_CONTRACT_VERSION,
            "version": REPORT_LINEAGE_METHOD_VERSION,
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        return DesignAwareReportInputAuthority(
            f"rg-input-{fingerprint}", project_id, run_id, "DESIGN_AWARE_EXECUTION",
            finding_generation_record_id, findings.generation_fingerprint,
            insight_generation_record_id, insights.generation_fingerprint,
            re_input.authority_id, re_input.fingerprint,
            re_manifest.manifest_id, re_manifest.fingerprint,
            re_coverage.coverage_id, re_coverage.fingerprint,
            rf_input.authority_id, rf_input.fingerprint,
            rf_manifest.manifest_id, rf_manifest.fingerprint,
            rf_coverage.coverage_id, rf_coverage.fingerprint,
            re_input.rd_execution_manifest_id, re_input.rd_execution_manifest_fingerprint,
            re_input.rc_plan_id, re_input.rc_plan_version_id, re_input.rc_plan_fingerprint,
            re_input.dataset_version_id, re_input.dataset_fingerprint,
            re_input.codebook_version_id, re_input.codebook_fingerprint,
            finding_entries, insight_entries, re_input.analytical_requirement_ids,
            constraints, limitations, REPORT_COMPOSITION_CONTRACT_VERSION,
            REPORT_LINEAGE_METHOD_VERSION, fingerprint,
        )

    def report_bundle(self, authority):
        return {
            "findings": tuple(item.safe_finding_projection for item in authority.finding_entries),
            "insights": tuple(item.safe_insight_projection for item in authority.insight_entries),
            "deliverable_constraints": authority.deliverable_constraints,
            "limitations": authority.limitations,
        }

    def expected_report_bundle_fingerprint(self, authority):
        return canonical_digest(self.report_bundle(authority), digest_provider=self.digest)

    def compatibility_validator(self, authority):
        def validate(report):
            self._section_entries(authority, report)
            return report
        return validate

    def finalize(self, *, authority, report_composition_record_id, composition):
        if composition.input_support_bundle_fingerprint != self.expected_report_bundle_fingerprint(authority):
            raise QuantitativeReportLineageError("Report composition input authority mismatch")
        section_entries = ()
        manifest = None
        if composition.accepted_report is not None:
            section_entries = self._section_entries(authority, composition.accepted_report)
        coverage = self.repository.save_coverage(self._coverage(
            authority, report_composition_record_id, composition, section_entries
        ))
        if composition.accepted_report is not None:
            report = composition.accepted_report
            payload = {
                "composition": (report_composition_record_id, composition.composition_fingerprint),
                "report": (report.report_id, report.validation_fingerprint),
                "input": (authority.authority_id, authority.fingerprint),
                "re": (authority.re_lineage_manifest_id, authority.re_lineage_manifest_fingerprint, authority.re_coverage_id, authority.re_coverage_fingerprint),
                "rf": (authority.rf_lineage_manifest_id, authority.rf_lineage_manifest_fingerprint, authority.rf_coverage_id, authority.rf_coverage_fingerprint),
                "rd": (authority.rd_execution_manifest_id, authority.rd_execution_manifest_fingerprint),
                "rc": (authority.rc_plan_id, authority.rc_plan_fingerprint),
                "coverage": (coverage.coverage_id, coverage.fingerprint),
                "entries": tuple(item.fingerprint for item in section_entries),
                "version": REPORT_LINEAGE_METHOD_VERSION,
            }
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            manifest = self.repository.save_manifest(QuantitativeReportDesignLineageManifest(
                f"rg-lineage-{fingerprint}", authority.project_id, authority.run_id,
                report_composition_record_id, composition.composition_fingerprint,
                report.report_id, report.validation_fingerprint,
                authority.authority_id, authority.fingerprint,
                authority.re_lineage_manifest_id, authority.re_lineage_manifest_fingerprint,
                authority.re_coverage_id, authority.re_coverage_fingerprint,
                authority.rf_lineage_manifest_id, authority.rf_lineage_manifest_fingerprint,
                authority.rf_coverage_id, authority.rf_coverage_fingerprint,
                authority.rd_execution_manifest_id, authority.rd_execution_manifest_fingerprint,
                authority.rc_plan_id, authority.rc_plan_fingerprint,
                coverage.coverage_id, coverage.fingerprint, section_entries,
                REPORT_LINEAGE_METHOD_VERSION, fingerprint,
            ))
        return manifest, coverage

    def dataset_only_absence(self, *, project_id, run_id, report_composition_record_id, composition):
        payload = {
            "project": project_id, "run": run_id,
            "composition": (report_composition_record_id, composition.composition_fingerprint),
            "status": "NO_DESIGN_AWARE_REPORT_LINEAGE",
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        return self.repository.save_dataset_only_absence(DatasetOnlyReportLineageAbsence(
            f"rg-absence-{fingerprint}", project_id, run_id,
            report_composition_record_id, composition.composition_fingerprint,
            "NO_DESIGN_AWARE_REPORT_LINEAGE", fingerprint,
        ))

    def design_aware_controlled_absence(
        self, *, project_id, run_id, generation_record_id, generation,
        rf_absence, re_manifest,
    ):
        if any(
            item.project_id != project_id or item.run_id != run_id
            for item in (rf_absence, re_manifest)
        ):
            raise QuantitativeReportLineageError(
                "RG controlled absence project/run mismatch"
            )
        if generation.accepted_findings:
            raise QuantitativeReportLineageError(
                "RG controlled absence contradicts accepted Finding authority"
            )
        if re_manifest.entries:
            raise QuantitativeReportLineageError(
                "RG controlled absence contradicts RE Finding lineage"
            )
        reason = DesignAwareReportAbsenceReason.NO_SUPPORTED_FINDINGS
        if (
            rf_absence.finding_generation_record_id != generation_record_id
            or rf_absence.finding_generation_fingerprint
            != generation.generation_fingerprint
            or rf_absence.re_lineage_manifest_id != re_manifest.manifest_id
            or rf_absence.re_lineage_manifest_fingerprint != re_manifest.fingerprint
            or rf_absence.reason.value != reason.value
        ):
            raise QuantitativeReportLineageError(
                "RG controlled absence upstream mismatch"
            )
        payload = {
            "project": project_id,
            "run": run_id,
            "generation": (generation_record_id, generation.generation_fingerprint),
            "rf_absence": (rf_absence.absence_id, rf_absence.fingerprint),
            "re_lineage": (re_manifest.manifest_id, re_manifest.fingerprint),
            "rd": (
                rf_absence.rd_execution_manifest_id,
                rf_absence.rd_execution_manifest_fingerprint,
            ),
            "rc": (rf_absence.rc_plan_id, rf_absence.rc_plan_fingerprint),
            "reason": reason.value,
            "version": REPORT_LINEAGE_METHOD_VERSION,
        }
        fp = canonical_digest(payload, digest_provider=self.digest)
        value = DesignAwareReportControlledAbsence(
            f"rg-controlled-absence-{fp}", project_id, run_id,
            generation_record_id, generation.generation_fingerprint,
            rf_absence.absence_id, rf_absence.fingerprint,
            re_manifest.manifest_id, re_manifest.fingerprint,
            rf_absence.rd_execution_manifest_id,
            rf_absence.rd_execution_manifest_fingerprint,
            rf_absence.rc_plan_id, rf_absence.rc_plan_fingerprint,
            reason, REPORT_LINEAGE_METHOD_VERSION, fp,
        )
        return self.repository.save_controlled_absence(value)

    def _section_entries(self, authority, report):
        findings = {item.finding_id: item for item in authority.finding_entries}
        insights = {item.insight_id: item for item in authority.insight_entries}
        entries = []
        for section in report.sections:
            selected_findings = []
            selected_insights = []
            for reference in section.finding_refs:
                item = findings.get(reference.authority_id)
                if item is None or item.qh_validation_fingerprint != reference.validation_fingerprint:
                    raise QuantitativeReportLineageError("section Finding is outside RG authority")
                selected_findings.append(item)
            for reference in section.insight_refs:
                item = insights.get(reference.authority_id)
                if item is None or item.qj_validation_fingerprint != reference.validation_fingerprint:
                    raise QuantitativeReportLineageError("section Insight is outside RG authority")
                selected_insights.append(item)
            effective = {}
            for item in selected_findings:
                for branch in item.branches:
                    effective[(item.finding_id, self._branch_payload(branch))] = ("FINDING", item.finding_id, branch)
            for insight in selected_insights:
                for finding_id, branches in insight.branches_by_finding:
                    for branch in branches:
                        effective.setdefault((finding_id, self._branch_payload(branch)), ("INSIGHT", insight.insight_id, branch))
            if not effective:
                raise QuantitativeReportLineageError("Report section lacks design-aware support")
            requirement_sets = [
                {value for branch in item.branches for value in branch.analytical_requirement_ids}
                for item in selected_findings
            ] + [set(item.common_analytical_requirement_ids) for item in selected_insights]
            question_sets = [
                {value for branch in item.branches for value in branch.research_question_ids}
                for item in selected_findings
            ] + [set(item.common_research_question_ids) for item in selected_insights]
            common_requirements = tuple(sorted(set.intersection(*requirement_sets)))
            common_questions = tuple(sorted(set.intersection(*question_sets))) if not common_requirements else ()
            if not common_requirements and not common_questions:
                raise QuantitativeReportLineageError("Report section support lacks a common requirement or ResearchQuestion")
            objectives = set()
            branches = []
            for (finding_id, _), (kind, support_id, branch) in sorted(effective.items()):
                if set(branch.analytical_requirement_ids).intersection(common_requirements) or set(branch.research_question_ids).intersection(common_questions):
                    objectives.update(branch.objective_ids)
                branches.append(ReportSectionEffectiveSupportBranch(kind, support_id, finding_id, branch))
            support_payload = {
                "section": section.section_id,
                "findings": tuple((item.finding_id, item.qh_validation_fingerprint) for item in selected_findings),
                "insights": tuple((item.insight_id, item.qj_validation_fingerprint) for item in selected_insights),
                "branches": tuple((item.support_kind, item.support_id, item.finding_id, self._branch_payload(item.branch)) for item in branches),
            }
            support_fp = canonical_digest(support_payload, digest_provider=self.digest)
            payload = {**support_payload, "scope": (common_requirements, common_questions, tuple(sorted(objectives))), "version": REPORT_LINEAGE_METHOD_VERSION}
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            entries.append(ReportSectionDesignLineageEntry(
                section.section_id, support_fp,
                tuple((item.finding_id, item.qh_validation_fingerprint) for item in selected_findings),
                tuple((item.insight_id, item.qj_validation_fingerprint) for item in selected_insights),
                tuple(sorted({item.re_lineage_entry_fingerprint for item in selected_findings})),
                tuple(sorted({item.rf_lineage_entry_fingerprint for item in selected_insights})),
                tuple(branches), common_requirements, common_questions,
                tuple(sorted(objectives)), fingerprint,
            ))
        return tuple(entries)

    def _coverage(self, authority, record_id, composition, section_entries):
        supported = {value for item in authority.finding_entries for branch in item.branches for value in branch.analytical_requirement_ids}
        supported.update(value for item in authority.insight_entries for _, branches in item.branches_by_finding for branch in branches for value in branch.analytical_requirement_ids)
        covered = {}
        for entry in section_entries:
            for branch in entry.effective_support_branches:
                if set(branch.branch.analytical_requirement_ids).intersection(entry.common_analytical_requirement_ids) or set(branch.branch.research_question_ids).intersection(entry.common_research_question_ids):
                    for requirement in branch.branch.analytical_requirement_ids:
                        covered.setdefault(requirement, set()).add(entry.section_id)
        entries = []
        for requirement in authority.analytical_requirement_ids:
            sections = tuple(sorted(covered.get(requirement, ())))
            finding_ids = tuple(sorted({item.finding_id for item in authority.finding_entries if any(requirement in branch.analytical_requirement_ids for branch in item.branches)}))
            insight_ids = tuple(sorted({item.insight_id for item in authority.insight_entries if any(requirement in branch.analytical_requirement_ids for _, branches in item.branches_by_finding for branch in branches)}))
            if sections:
                status, rationale = ReportCoverageStatus.REPORT_COVERED, "An accepted QK section represents supported content for this requirement."
            elif requirement not in supported:
                status, rationale = ReportCoverageStatus.NO_SUPPORTED_CONTENT, "No accepted Finding or Insight supports this requirement."
            elif composition.accepted_report is None:
                status, rationale = ReportCoverageStatus.REPORT_PROPOSAL_REJECTED, "Supported content existed, but no QK proposal was accepted."
            else:
                status, rationale = ReportCoverageStatus.SUPPORTED_CONTENT_NOT_REPORTED, "Supported content exists but is not represented by an accepted section."
            entries.append(ReportCoverageEntry(requirement, status, sections, finding_ids, insight_ids, rationale))
        payload = {
            "input": (authority.authority_id, authority.fingerprint),
            "composition": (record_id, composition.composition_fingerprint),
            "entries": tuple((item.analytical_requirement_id, item.status.value, item.section_ids, item.finding_ids, item.insight_ids) for item in entries),
            "version": REPORT_LINEAGE_METHOD_VERSION,
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        return QuantitativeReportCoverageManifest(
            f"rg-coverage-{fingerprint}", authority.project_id, authority.run_id,
            authority.authority_id, authority.fingerprint, record_id,
            composition.composition_fingerprint, tuple(entries),
            REPORT_LINEAGE_METHOD_VERSION, fingerprint,
        )

    @staticmethod
    def _preflight(project_id, run_id, finding_record, findings, insight_record, insights, re_input, re_manifest, re_coverage, rf_input, rf_manifest, rf_coverage):
        values = (re_input, re_manifest, re_coverage, rf_input, rf_manifest, rf_coverage)
        if any(item.project_id != project_id or item.run_id != run_id for item in values):
            raise QuantitativeReportLineageError("RG authority project/run mismatch")
        if rf_input.execution_mode != "DESIGN_AWARE_EXECUTION":
            raise QuantitativeReportLineageError("design-aware QK requires design-aware RF authority")
        if re_manifest.finding_generation_record_id != finding_record or re_manifest.finding_generation_fingerprint != findings.generation_fingerprint:
            raise QuantitativeReportLineageError("Finding generation authority mismatch")
        if rf_manifest.insight_generation_record_id != insight_record or rf_manifest.insight_generation_fingerprint != insights.generation_fingerprint:
            raise QuantitativeReportLineageError("Insight generation authority mismatch")
        if (rf_input.finding_generation_record_id != finding_record or rf_input.finding_generation_fingerprint != findings.generation_fingerprint):
            raise QuantitativeReportLineageError("stale RF input Finding authority")
        if (re_manifest.input_authority_id, re_manifest.input_authority_fingerprint) != (re_input.authority_id, re_input.fingerprint) or (re_manifest.coverage_manifest_id, re_manifest.coverage_manifest_fingerprint) != (re_coverage.coverage_id, re_coverage.fingerprint):
            raise QuantitativeReportLineageError("stale RE authority")
        if (rf_manifest.input_authority_id, rf_manifest.input_authority_fingerprint) != (rf_input.authority_id, rf_input.fingerprint) or (rf_manifest.coverage_manifest_id, rf_manifest.coverage_manifest_fingerprint) != (rf_coverage.coverage_id, rf_coverage.fingerprint):
            raise QuantitativeReportLineageError("stale RF authority")
        if (rf_input.re_lineage_manifest_id, rf_input.re_lineage_manifest_fingerprint, rf_input.re_coverage_id, rf_input.re_coverage_fingerprint) != (re_manifest.manifest_id, re_manifest.fingerprint, re_coverage.coverage_id, re_coverage.fingerprint):
            raise QuantitativeReportLineageError("RF does not bind exact RE authority")
        if (rf_input.rd_execution_manifest_id, rf_input.rd_execution_manifest_fingerprint, rf_input.rc_plan_id, rf_input.rc_plan_version_id, rf_input.rc_plan_fingerprint) != (re_input.rd_execution_manifest_id, re_input.rd_execution_manifest_fingerprint, re_input.rc_plan_id, re_input.rc_plan_version_id, re_input.rc_plan_fingerprint):
            raise QuantitativeReportLineageError("stale RD/RC authority")

    @staticmethod
    def _finding_projection(item):
        return {"finding_id": item.finding_id, "validation_fingerprint": item.support_validation_fingerprint, "text": item.text, "claim_type": item.claim.claim_type.value, "display_value": item.claim.display_value, "direction": item.claim.direction, "context": item.analytical_context_fingerprint, "weighting": item.claim.weighting_status, "filter": item.claim.filter_definition, "base": item.claim.base_definition, "result_refs": tuple(ref.result_id for ref in item.statistical_result_refs)}

    @staticmethod
    def _insight_projection(item):
        return {"insight_id": item.insight_id, "validation_fingerprint": item.validation_fingerprint, "text": item.insight_text, "type": item.insight_type.value, "finding_refs": tuple(ref.finding_id for ref in item.supporting_finding_refs), "display_values": item.referenced_display_values, "context": item.support_context_fingerprint, "limitation": item.limitation_note}

    @staticmethod
    def _branch_payload(item):
        return (item.rd_outcome_id, item.rd_outcome_fingerprint, item.planned_analysis_id, item.planned_comparison_id, item.objective_ids, item.research_question_ids, item.analytical_requirement_ids)
