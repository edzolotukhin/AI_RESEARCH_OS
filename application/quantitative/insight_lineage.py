from __future__ import annotations

from application.quantitative.fingerprints import canonical_digest
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import QuantitativeSupportStatus
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.insight_lineage import (
    INSIGHT_LINEAGE_METHOD_VERSION,
    DatasetOnlyInsightLineageAbsence,
    DesignAwareInsightFindingSupportEntry,
    DesignAwareInsightInputAuthority,
    InsightCoverageEntry,
    InsightCoverageStatus,
    InsightDesignLineageEntry,
    InsightFindingLineageBranch,
    QuantitativeInsightCoverageManifest,
    QuantitativeInsightDesignLineageManifest,
)


class QuantitativeInsightLineageError(QuantitativeAnalysisError):
    pass


class QuantitativeInsightLineageService:
    def __init__(self, *, repository, digest_provider) -> None:
        self.repository = repository
        self.digest = digest_provider

    def build_input_authority(self, *, project_id, run_id, generation_record_id, generation, re_input, re_manifest, re_coverage):
        self._preflight(project_id, run_id, generation_record_id, generation, re_input, re_manifest, re_coverage)
        re_entries = {item.finding_id: item for item in re_manifest.entries}
        if len(re_entries) != len(re_manifest.entries):
            raise QuantitativeInsightLineageError("duplicate RE Finding lineage")
        analysis = {item.rd_outcome_id: item for item in re_input.analysis_entries}
        comparisons = {item.rd_outcome_id: item for item in re_input.comparison_entries}
        entries = []
        for finding in generation.accepted_findings:
            lineage = re_entries.get(finding.finding_id)
            if lineage is None or lineage.qh_validation_fingerprint != finding.support_validation_fingerprint:
                raise QuantitativeInsightLineageError("accepted Finding lacks exact current RE lineage")
            branches = []
            limitations = []
            for outcome_id, outcome_fingerprint in lineage.rd_outcome_ids_and_fingerprints:
                support = analysis.get(outcome_id) or comparisons.get(outcome_id)
                if support is None or support.rd_outcome_fingerprint != outcome_fingerprint:
                    raise QuantitativeInsightLineageError("RE lineage branch is unavailable or altered")
                branches.append(InsightFindingLineageBranch(
                    outcome_id, outcome_fingerprint,
                    getattr(support, "planned_analysis_id", None),
                    getattr(support, "planned_comparison_id", None),
                    support.objective_ids, support.research_question_ids,
                    support.analytical_requirement_ids,
                ))
                limitations.extend(support.limitations)
            branches = tuple(sorted(branches, key=lambda item: (item.rd_outcome_id, item.planned_analysis_id or "", item.planned_comparison_id or "")))
            payload = {
                "finding": (finding.finding_id, finding.support_validation_fingerprint),
                "re": lineage.fingerprint,
                "branches": tuple(self._branch_payload(item) for item in branches),
                "version": INSIGHT_LINEAGE_METHOD_VERSION,
            }
            fp = canonical_digest(payload, digest_provider=self.digest)
            entries.append(DesignAwareInsightFindingSupportEntry(
                finding.finding_id, finding.support_validation_fingerprint,
                self._finding_projection(finding), lineage.fingerprint,
                lineage.statistical_result_ids_and_fingerprints,
                lineage.comparison_result_ids_and_fingerprints,
                branches, tuple(dict.fromkeys(limitations)), fp,
            ))
        entries = tuple(sorted(entries, key=lambda item: item.finding_id))
        requirements = tuple(sorted({value for item in entries for branch in item.branches for value in branch.analytical_requirement_ids}))
        limitations = tuple(dict.fromkeys(re_input.limitations + tuple(value for item in entries for value in item.limitations)))
        payload = {
            "project": project_id, "run": run_id,
            "generation": (generation_record_id, generation.generation_fingerprint),
            "re_manifest": (re_manifest.manifest_id, re_manifest.fingerprint),
            "re_input": (re_input.authority_id, re_input.fingerprint),
            "re_coverage": (re_coverage.coverage_id, re_coverage.fingerprint),
            "rd": (re_input.rd_execution_manifest_id, re_input.rd_execution_manifest_fingerprint),
            "rc": (re_input.rc_plan_id, re_input.rc_plan_version_id, re_input.rc_plan_fingerprint),
            "entries": tuple(item.fingerprint for item in entries),
            "requirements": requirements, "limitations": limitations,
            "version": INSIGHT_LINEAGE_METHOD_VERSION,
        }
        fp = canonical_digest(payload, digest_provider=self.digest)
        return DesignAwareInsightInputAuthority(
            f"rf-input-{fp}", project_id, run_id, "DESIGN_AWARE_EXECUTION",
            generation_record_id, generation.generation_fingerprint,
            re_manifest.manifest_id, re_manifest.fingerprint,
            re_input.authority_id, re_input.fingerprint,
            re_coverage.coverage_id, re_coverage.fingerprint,
            re_input.rd_execution_manifest_id, re_input.rd_execution_manifest_fingerprint,
            re_input.rc_plan_id, re_input.rc_plan_version_id, re_input.rc_plan_fingerprint,
            entries, requirements, limitations, INSIGHT_LINEAGE_METHOD_VERSION, fp,
        )

    def compatibility_validator(self, authority):
        available = {item.finding_id: item for item in authority.finding_entries}

        def validate(insight):
            selected = []
            for reference in insight.supporting_finding_refs:
                entry = available.get(reference.finding_id)
                if entry is None or entry.qh_validation_fingerprint != reference.support_validation_fingerprint:
                    raise QuantitativeInsightLineageError("Insight references Finding outside RF authority")
                selected.append(entry)
            self._common_scope(selected)
            return insight
        return validate

    def expected_generation_bundle_fingerprint(self, authority):
        bundle = tuple(item.safe_finding_projection for item in authority.finding_entries)
        return canonical_digest(bundle, digest_provider=self.digest)

    def finalize(self, *, authority, generation_record_id, generation: QuantitativeInsightGenerationResult):
        if generation.input_finding_bundle_fingerprint != self.expected_generation_bundle_fingerprint(authority):
            raise QuantitativeInsightLineageError("Insight generation input authority mismatch")
        available = {item.finding_id: item for item in authority.finding_entries}
        entries = []
        for insight in generation.accepted_insights:
            selected = []
            for reference in insight.supporting_finding_refs:
                item = available.get(reference.finding_id)
                if item is None or item.qh_validation_fingerprint != reference.support_validation_fingerprint:
                    raise QuantitativeInsightLineageError("accepted Insight references unauthorized Finding")
                selected.append(item)
            common_requirements, common_questions, common_objectives = self._common_scope(selected)
            payload = {
                "insight": (insight.insight_id, insight.validation_fingerprint),
                "findings": tuple((item.finding_id, item.qh_validation_fingerprint, item.re_lineage_entry_fingerprint) for item in selected),
                "branches": tuple((item.finding_id, tuple(self._branch_payload(branch) for branch in item.branches)) for item in selected),
                "scope": (common_requirements, common_questions, common_objectives),
                "version": INSIGHT_LINEAGE_METHOD_VERSION,
            }
            fp = canonical_digest(payload, digest_provider=self.digest)
            entries.append(InsightDesignLineageEntry(
                insight.insight_id, insight.validation_fingerprint,
                tuple(item.finding_id for item in selected),
                tuple(item.qh_validation_fingerprint for item in selected),
                tuple(item.re_lineage_entry_fingerprint for item in selected),
                tuple((item.finding_id, item.branches) for item in selected),
                common_requirements, common_questions, common_objectives, fp,
            ))
        entries = tuple(sorted(entries, key=lambda item: item.insight_id))
        coverage = self.repository.save_coverage(self._coverage(authority, generation, entries))
        payload = {
            "generation": (generation_record_id, generation.generation_fingerprint),
            "input": (authority.authority_id, authority.fingerprint),
            "re": (authority.re_lineage_manifest_id, authority.re_lineage_manifest_fingerprint),
            "coverage": (coverage.coverage_id, coverage.fingerprint),
            "entries": tuple(item.fingerprint for item in entries),
            "version": INSIGHT_LINEAGE_METHOD_VERSION,
        }
        fp = canonical_digest(payload, digest_provider=self.digest)
        manifest = QuantitativeInsightDesignLineageManifest(
            f"rf-lineage-{fp}", authority.project_id, authority.run_id,
            generation_record_id, generation.generation_fingerprint,
            authority.authority_id, authority.fingerprint,
            authority.re_lineage_manifest_id, authority.re_lineage_manifest_fingerprint,
            authority.re_coverage_id, authority.re_coverage_fingerprint,
            authority.rd_execution_manifest_id, authority.rd_execution_manifest_fingerprint,
            authority.rc_plan_id, authority.rc_plan_fingerprint,
            coverage.coverage_id, coverage.fingerprint, entries,
            INSIGHT_LINEAGE_METHOD_VERSION, fp,
        )
        return self.repository.save_manifest(manifest), coverage

    def dataset_only_absence(self, *, project_id, run_id, generation_record_id, generation):
        payload = {"project": project_id, "run": run_id, "generation": generation.generation_fingerprint, "status": "NO_DESIGN_AWARE_INSIGHT_LINEAGE"}
        fp = canonical_digest(payload, digest_provider=self.digest)
        return self.repository.save_dataset_only_absence(DatasetOnlyInsightLineageAbsence(
            f"rf-absence-{fp}", project_id, run_id, generation_record_id,
            generation.generation_fingerprint, "NO_DESIGN_AWARE_INSIGHT_LINEAGE", fp,
        ))

    @staticmethod
    def _preflight(project_id, run_id, generation_record_id, generation, re_input, re_manifest, re_coverage):
        values = (re_input, re_manifest, re_coverage)
        if any(item.project_id != project_id or item.run_id != run_id for item in values):
            raise QuantitativeInsightLineageError("RF authority project/run mismatch")
        if re_manifest.finding_generation_record_id != generation_record_id or re_manifest.finding_generation_fingerprint != generation.generation_fingerprint:
            raise QuantitativeInsightLineageError("Finding generation authority mismatch")
        if re_manifest.input_authority_id != re_input.authority_id or re_manifest.input_authority_fingerprint != re_input.fingerprint:
            raise QuantitativeInsightLineageError("stale RE input authority")
        if re_manifest.coverage_manifest_id != re_coverage.coverage_id or re_manifest.coverage_manifest_fingerprint != re_coverage.fingerprint:
            raise QuantitativeInsightLineageError("stale RE coverage authority")

    @staticmethod
    def _finding_projection(item):
        return {
            "finding_id": item.finding_id,
            "support_validation_fingerprint": item.support_validation_fingerprint,
            "analytical_context_fingerprint": item.analytical_context_fingerprint,
            "claim_type": item.claim.claim_type.value, "finding_text": item.text,
            "display_value": item.claim.display_value, "direction": item.claim.direction,
            "filter_definition": item.claim.filter_definition, "base_definition": item.claim.base_definition,
            "weighting_status": item.claim.weighting_status, "weight_set_fingerprint": item.claim.weight_set_fingerprint,
        }

    @staticmethod
    def _branch_payload(item):
        return (
            item.rd_outcome_id, item.rd_outcome_fingerprint,
            item.planned_analysis_id, item.planned_comparison_id,
            item.objective_ids, item.research_question_ids,
            item.analytical_requirement_ids,
        )

    @staticmethod
    def _common_scope(entries):
        if not entries:
            raise QuantitativeInsightLineageError("Insight requires RF Finding support")
        requirement_sets = [{value for branch in item.branches for value in branch.analytical_requirement_ids} for item in entries]
        question_sets = [{value for branch in item.branches for value in branch.research_question_ids} for item in entries]
        common_requirements = tuple(sorted(set.intersection(*requirement_sets)))
        common_questions = tuple(sorted(set.intersection(*question_sets)))
        if not common_requirements and not common_questions:
            raise QuantitativeInsightLineageError("supporting Findings lack a common requirement or ResearchQuestion")
        objectives = set()
        for item in entries:
            for branch in item.branches:
                if set(branch.analytical_requirement_ids).intersection(common_requirements) or set(branch.research_question_ids).intersection(common_questions):
                    objectives.update(branch.objective_ids)
        return common_requirements, common_questions, tuple(sorted(objectives))

    def _coverage(self, authority, generation, lineage_entries):
        by_requirement = {item: [] for item in authority.analytical_requirement_ids}
        finding_by_requirement = {item: set() for item in authority.analytical_requirement_ids}
        for item in authority.finding_entries:
            for branch in item.branches:
                for requirement in branch.analytical_requirement_ids:
                    finding_by_requirement.setdefault(requirement, set()).add(item.finding_id)
        for entry in lineage_entries:
            for requirement in entry.common_analytical_requirement_ids:
                by_requirement.setdefault(requirement, []).append(entry.insight_id)
            if not entry.common_analytical_requirement_ids:
                for _, branches in entry.branches_by_finding:
                    for branch in branches:
                        if set(branch.research_question_ids).intersection(entry.common_research_question_ids):
                            for requirement in branch.analytical_requirement_ids:
                                by_requirement.setdefault(requirement, []).append(entry.insight_id)
        entries = []
        incompatible = any("common requirement or ResearchQuestion" in item.reason for item in generation.rejected_insights)
        for requirement in authority.analytical_requirement_ids:
            insight_ids = tuple(sorted(set(by_requirement.get(requirement, ()))))
            finding_ids = tuple(sorted(finding_by_requirement.get(requirement, set())))
            if insight_ids: status, rationale = InsightCoverageStatus.INSIGHT_SUPPORTED, "One or more QJ-supported RF-compatible Insights retain this requirement branch."
            elif not finding_ids: status, rationale = InsightCoverageStatus.BLOCKED_NO_SUPPORTED_FINDING, "No RE-supported Finding is available for this requirement."
            elif incompatible: status, rationale = InsightCoverageStatus.INCOMPATIBLE_FINDING_CONTEXT, "Selected Findings did not share a compatible requirement or ResearchQuestion scope."
            elif generation.acceptance_summary.get("proposed", 0) == 0: status, rationale = InsightCoverageStatus.NO_INSIGHT_PROPOSED, "QJ proposed no Insight for available Finding support."
            else: status, rationale = InsightCoverageStatus.PROPOSALS_REJECTED_UNSUPPORTED, "No proposal passed QJ and RF authority."
            entries.append(InsightCoverageEntry(requirement, status, insight_ids, finding_ids, rationale))
        payload = {"input": (authority.authority_id, authority.fingerprint), "generation": generation.generation_fingerprint, "entries": tuple((x.analytical_requirement_id, x.status.value, x.insight_ids, x.finding_ids) for x in entries), "version": INSIGHT_LINEAGE_METHOD_VERSION}
        fp = canonical_digest(payload, digest_provider=self.digest)
        return QuantitativeInsightCoverageManifest(f"rf-coverage-{fp}", authority.project_id, authority.run_id, authority.authority_id, authority.fingerprint, generation.generation_fingerprint, tuple(entries), INSIGHT_LINEAGE_METHOD_VERSION, fp)
