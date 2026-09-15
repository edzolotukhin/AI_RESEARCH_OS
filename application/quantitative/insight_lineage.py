from __future__ import annotations

from dataclasses import replace

from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.insight_support_canonicalization import (
    canonical_finding_support_bundle,
    finding_support_projection,
    validate_finding_semantic_context,
)
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from application.quantitative.insight_synthesis import (
    PROMPT_VERSION as INSIGHT_PROMPT_VERSION,
    VALIDATION_VERSION as INSIGHT_VALIDATION_VERSION,
)
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeSupportStatus
from domain.quantitative.finding_lineage import FindingCoverageStatus
from domain.quantitative.insight import (
    QuantitativeInsightCompatibilityMode,
    QuantitativeInsightGenerationResult,
    QuantitativeInsightType,
)
from domain.quantitative.insight_lineage import (
    INSIGHT_LINEAGE_METHOD_VERSION,
    DatasetOnlyInsightLineageAbsence,
    DesignAwareInsightAbsenceReason,
    DesignAwareInsightControlledAbsence,
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
            try:
                validate_finding_semantic_context(
                    finding, digest_provider=self.digest
                )
            except QuantitativeAnalysisError as exc:
                raise QuantitativeInsightLineageError(str(exc)) from exc
            lineage = re_entries.get(finding.finding_id)
            if lineage is None or lineage.qh_validation_fingerprint != finding.support_validation_fingerprint:
                raise QuantitativeInsightLineageError("accepted Finding lacks exact current RE lineage")
            branches = []
            limitations = []
            resolved_supports = []
            for outcome_id, outcome_fingerprint in lineage.rd_outcome_ids_and_fingerprints:
                support = analysis.get(outcome_id) or comparisons.get(outcome_id)
                if support is None or support.rd_outcome_fingerprint != outcome_fingerprint:
                    raise QuantitativeInsightLineageError("RE lineage branch is unavailable or altered")
                resolved_supports.append(support)
                branches.append(InsightFindingLineageBranch(
                    outcome_id, outcome_fingerprint,
                    getattr(support, "planned_analysis_id", None),
                    getattr(support, "planned_comparison_id", None),
                    support.objective_ids, support.research_question_ids,
                    support.analytical_requirement_ids,
                ))
                limitations.extend(support.limitations)
            branches = tuple(sorted(branches, key=lambda item: (item.rd_outcome_id, item.planned_analysis_id or "", item.planned_comparison_id or "")))
            interpretive_context = self._interpretive_context(
                finding, resolved_supports, project_id=project_id, run_id=run_id,
                dataset_version_id=re_input.dataset_version_id,
                dataset_fingerprint=re_input.dataset_fingerprint,
                codebook_version_id=re_input.codebook_version_id,
                codebook_fingerprint=re_input.codebook_fingerprint,
            )
            payload = {
                "finding": (finding.finding_id, finding.support_validation_fingerprint),
                "re": lineage.fingerprint,
                "branches": tuple(self._branch_payload(item) for item in branches),
                "interpretive_context": interpretive_context,
                "version": INSIGHT_LINEAGE_METHOD_VERSION,
            }
            fp = canonical_digest(payload, digest_provider=self.digest)
            entries.append(DesignAwareInsightFindingSupportEntry(
                finding.finding_id, finding.support_validation_fingerprint,
                self._finding_projection(finding), lineage.fingerprint,
                lineage.statistical_result_ids_and_fingerprints,
                lineage.comparison_result_ids_and_fingerprints,
                branches, tuple(dict.fromkeys(limitations)), fp,
                interpretive_context=interpretive_context,
            ))
        entries = tuple(sorted(entries, key=lambda item: item.finding_id))
        requirements = tuple(sorted({value for item in entries for branch in item.branches for value in branch.analytical_requirement_ids}))
        limitations = tuple(dict.fromkeys(re_input.limitations + tuple(value for item in entries for value in item.limitations)))
        payload = self._input_authority_payload(
            project_id=project_id, run_id=run_id,
            generation_record_id=generation_record_id,
            generation_fingerprint=generation.generation_fingerprint,
            re_manifest_id=re_manifest.manifest_id,
            re_manifest_fingerprint=re_manifest.fingerprint,
            re_input_id=re_input.authority_id,
            re_input_fingerprint=re_input.fingerprint,
            re_coverage_id=re_coverage.coverage_id,
            re_coverage_fingerprint=re_coverage.fingerprint,
            rd_execution_manifest_id=re_input.rd_execution_manifest_id,
            rd_execution_manifest_fingerprint=re_input.rd_execution_manifest_fingerprint,
            rc_plan_id=re_input.rc_plan_id,
            rc_plan_version_id=re_input.rc_plan_version_id,
            rc_plan_fingerprint=re_input.rc_plan_fingerprint,
            entries=entries, requirements=requirements, limitations=limitations,
        )
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

    @staticmethod
    def _input_authority_payload(
        *, project_id, run_id, generation_record_id, generation_fingerprint,
        re_manifest_id, re_manifest_fingerprint, re_input_id,
        re_input_fingerprint, re_coverage_id, re_coverage_fingerprint,
        rd_execution_manifest_id, rd_execution_manifest_fingerprint,
        rc_plan_id, rc_plan_version_id, rc_plan_fingerprint, entries,
        requirements, limitations,
    ):
        return {
            "project": project_id, "run": run_id,
            "generation": (generation_record_id, generation_fingerprint),
            "re_manifest": (re_manifest_id, re_manifest_fingerprint),
            "re_input": (re_input_id, re_input_fingerprint),
            "re_coverage": (re_coverage_id, re_coverage_fingerprint),
            "rd": (rd_execution_manifest_id, rd_execution_manifest_fingerprint),
            "rc": (rc_plan_id, rc_plan_version_id, rc_plan_fingerprint),
            "entries": tuple(item.fingerprint for item in entries),
            "requirements": requirements, "limitations": limitations,
            "version": INSIGHT_LINEAGE_METHOD_VERSION,
        }

    def _validate_input_authority(self, authority):
        payload = self._input_authority_payload(
            project_id=authority.project_id, run_id=authority.run_id,
            generation_record_id=authority.finding_generation_record_id,
            generation_fingerprint=authority.finding_generation_fingerprint,
            re_manifest_id=authority.re_lineage_manifest_id,
            re_manifest_fingerprint=authority.re_lineage_manifest_fingerprint,
            re_input_id=authority.re_input_authority_id,
            re_input_fingerprint=authority.re_input_authority_fingerprint,
            re_coverage_id=authority.re_coverage_id,
            re_coverage_fingerprint=authority.re_coverage_fingerprint,
            rd_execution_manifest_id=authority.rd_execution_manifest_id,
            rd_execution_manifest_fingerprint=authority.rd_execution_manifest_fingerprint,
            rc_plan_id=authority.rc_plan_id,
            rc_plan_version_id=authority.rc_plan_version_id,
            rc_plan_fingerprint=authority.rc_plan_fingerprint,
            entries=authority.finding_entries,
            requirements=authority.analytical_requirement_ids,
            limitations=authority.limitations,
        )
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        if (
            authority.method_version != INSIGHT_LINEAGE_METHOD_VERSION
            or authority.fingerprint != fingerprint
            or authority.authority_id != f"rf-input-{fingerprint}"
        ):
            raise QuantitativeInsightLineageError("stale or malformed RF input authority")
    def compatibility_validator(self, authority):
        self._validate_input_authority(authority)
        available = {item.finding_id: item for item in authority.finding_entries}

        def validate(insight):
            if (
                insight.compatibility_mode
                or insight.compatibility_authority_id
                or insight.compatibility_authority_fingerprint
            ):
                raise QuantitativeInsightLineageError(
                    "Insight contains predeclared compatibility authority"
                )
            selected = []
            for reference in insight.supporting_finding_refs:
                entry = available.get(reference.finding_id)
                if entry is None or entry.qh_validation_fingerprint != reference.support_validation_fingerprint:
                    raise QuantitativeInsightLineageError("Insight references Finding outside RF authority")
                selected.append(entry)
            common_requirements, common_questions, common_objectives = self._common_scope(selected)
            contexts = {
                item.safe_finding_projection.get("analytical_context_fingerprint")
                for item in selected
            }
            if "" in contexts or None in contexts:
                raise QuantitativeInsightLineageError(
                    "supporting Findings lack analytical context authority"
                )
            if len(contexts) == 1:
                return insight
            if insight.insight_type is not QuantitativeInsightType.SYNTHESIS:
                raise QuantitativeInsightLineageError(
                    "cross-item compatibility is limited to descriptive synthesis"
                )
            dimensions = tuple(item.interpretive_context for item in selected)
            if any(not isinstance(item, dict) or not item for item in dimensions):
                raise QuantitativeInsightLineageError(
                    "supporting Findings lack interpretive compatibility authority"
                )
            if any(
                item.get("claim_type") != QuantitativeClaimType.DESCRIPTIVE_VALUE.value
                for item in dimensions
            ):
                raise QuantitativeInsightLineageError(
                    "cross-item compatibility is limited to descriptive Findings"
                )
            shared = dimensions[0]
            if any(item != shared for item in dimensions[1:]):
                raise QuantitativeInsightLineageError(
                    "supporting Findings have incompatible interpretive dimensions"
                )
            payload = {
                "mode": QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value,
                "project": authority.project_id,
                "run": authority.run_id,
                "rf_input": (authority.authority_id, authority.fingerprint),
                "findings": tuple(sorted(
                    (
                        item.finding_id,
                        item.qh_validation_fingerprint,
                        item.safe_finding_projection["analytical_context_fingerprint"],
                        item.fingerprint,
                    )
                    for item in selected
                )),
                "shared_scope": (
                    common_requirements,
                    common_questions,
                    common_objectives,
                ),
                "shared_dimensions": shared,
                "version": "P1_29_INTERPRETIVE_COMPATIBILITY_V1",
            }
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            return replace(
                insight,
                compatibility_mode=QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value,
                compatibility_authority_id=f"qj-compat-{fingerprint}",
                compatibility_authority_fingerprint=fingerprint,
            )
        return validate

    def expected_generation_bundle_fingerprint(self, authority):
        bundle = canonical_finding_support_bundle(
            authority.finding_entries,
            projection=lambda item: item.safe_finding_projection,
        )
        return canonical_digest(bundle, digest_provider=self.digest)

    @staticmethod
    def is_current_generation(generation: QuantitativeInsightGenerationResult) -> bool:
        return (
            generation.prompt_version == INSIGHT_PROMPT_VERSION
            and all(
                insight.validation_version == INSIGHT_VALIDATION_VERSION
                for insight in generation.accepted_insights
            )
        )

    def validate_generation_contract(self, generation: QuantitativeInsightGenerationResult) -> None:
        if not self.is_current_generation(generation):
            raise QuantitativeInsightLineageError(
                "stale Quantitative Insight generation contract"
            )

    def finalize(self, *, authority, generation_record_id, generation: QuantitativeInsightGenerationResult):
        self.validate_generation_contract(generation)
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
                "compatibility": (
                    insight.compatibility_mode, insight.compatibility_authority_id,
                    insight.compatibility_authority_fingerprint,
                ),
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
                insight.compatibility_mode, insight.compatibility_authority_id,
                insight.compatibility_authority_fingerprint,
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

    def design_aware_controlled_absence(
        self, *, project_id, run_id, generation_record_id, generation,
        re_input, re_manifest, re_coverage,
    ):
        self._preflight(
            project_id, run_id, generation_record_id, generation,
            re_input, re_manifest, re_coverage,
        )
        if generation.accepted_findings:
            raise QuantitativeInsightLineageError(
                "RF controlled absence contradicts accepted Finding authority"
            )
        if re_manifest.entries or any(
            item.status is FindingCoverageStatus.FINDING_SUPPORTED
            or item.finding_ids
            for item in re_coverage.entries
        ):
            raise QuantitativeInsightLineageError(
                "RF controlled absence contradicts RE Finding support"
            )
        reason = DesignAwareInsightAbsenceReason.NO_SUPPORTED_FINDINGS
        payload = {
            "project": project_id,
            "run": run_id,
            "generation": (generation_record_id, generation.generation_fingerprint),
            "re_input": (re_input.authority_id, re_input.fingerprint),
            "re_lineage": (re_manifest.manifest_id, re_manifest.fingerprint),
            "re_coverage": (re_coverage.coverage_id, re_coverage.fingerprint),
            "rd": (
                re_input.rd_execution_manifest_id,
                re_input.rd_execution_manifest_fingerprint,
            ),
            "rc": (re_input.rc_plan_id, re_input.rc_plan_fingerprint),
            "reason": reason.value,
            "version": INSIGHT_LINEAGE_METHOD_VERSION,
        }
        fp = canonical_digest(payload, digest_provider=self.digest)
        value = DesignAwareInsightControlledAbsence(
            f"rf-controlled-absence-{fp}", project_id, run_id,
            generation_record_id, generation.generation_fingerprint,
            re_input.authority_id, re_input.fingerprint,
            re_manifest.manifest_id, re_manifest.fingerprint,
            re_coverage.coverage_id, re_coverage.fingerprint,
            re_input.rd_execution_manifest_id,
            re_input.rd_execution_manifest_fingerprint,
            re_input.rc_plan_id, re_input.rc_plan_fingerprint,
            reason, INSIGHT_LINEAGE_METHOD_VERSION, fp,
        )
        return self.repository.save_controlled_absence(value)

    @staticmethod
    def _interpretive_context(
        finding, supports, *, project_id, run_id, dataset_version_id,
        dataset_fingerprint, codebook_version_id, codebook_fingerprint,
    ):
        if (
            finding.claim.claim_type is not QuantitativeClaimType.DESCRIPTIVE_VALUE
            or len(supports) != 1
            or finding.semantic_evidence_context is None
        ):
            return {}
        numerical = supports[0].safe_numerical_projection
        semantic = finding.semantic_evidence_context
        if semantic.statistic_type != "GROUPED_CATEGORY_PERCENTAGE":
            return {}
        return {
            "project_id": project_id,
            "run_id": run_id,
            "dataset_version_id": dataset_version_id,
            "dataset_fingerprint": dataset_fingerprint,
            "codebook_version_id": codebook_version_id,
            "codebook_fingerprint": codebook_fingerprint,
            "analysis_family": "GROUPED_CATEGORY_DESCRIPTIVE",
            "claim_type": finding.claim.claim_type.value,
            "population_description": semantic.population_description,
            "base_definition": semantic.base_definition,
            "filter_definition": semantic.filter_definition,
            "weighting_status": semantic.weighting_status,
            "weight_set_fingerprint": semantic.weight_set_fingerprint,
            "missing_value_semantics": numerical.get("missing_value_semantics"),
            "statistic_type": semantic.statistic_type,
            "category_code": canonical_scalar(semantic.category_code),
            "category_label": semantic.category_label,
            "grouped_metric_semantic": semantic.grouped_metric_semantic,
            "grouped_category_members": tuple(
                canonical_scalar(item) for item in semantic.grouped_category_members
            ),
            "grouped_category_method_version": semantic.grouped_category_method_version,
        }
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
        return finding_support_projection(item)

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
