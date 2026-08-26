from __future__ import annotations

from decimal import Decimal

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.state_persistence import authority_fingerprint
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from domain.quantitative.analysis_execution import (
    AnalysisExecutionManifestStatus,
    AnalysisItemExecutionStatus,
    QuantitativeAnalysisExecutionMode,
)
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.finding_lineage import (
    FINDING_LINEAGE_METHOD_VERSION,
    DatasetOnlyFindingLineageAbsence,
    DesignAwareAnalysisSupportEntry,
    DesignAwareComparisonSupportEntry,
    DesignAwareFindingInputAuthority,
    FindingCoverageEntry,
    FindingCoverageStatus,
    FindingDesignLineageEntry,
    QuantitativeFindingCoverageManifest,
    QuantitativeFindingDesignLineageManifest,
)


class QuantitativeFindingLineageError(RuntimeError):
    pass


class QuantitativeFindingLineageService:
    def __init__(
        self,
        *,
        repository,
        analysis_execution_repository,
        state_service,
        digest_provider,
    ) -> None:
        self.repository = repository
        self.execution_repository = analysis_execution_repository
        self.state = state_service
        self.digest = digest_provider

    def build_input_authority(
        self,
        *,
        project_id,
        run_id,
        manifest,
        projection,
        dataset,
        codebook,
    ) -> DesignAwareFindingInputAuthority:
        self._preflight(project_id, run_id, manifest, projection, dataset, codebook)
        coverage = self.execution_repository.get_coverage(
            manifest.coverage_manifest_id, project_id=project_id
        )
        if coverage is None or coverage.fingerprint != manifest.coverage_manifest_fingerprint:
            raise QuantitativeFindingLineageError("stale RD execution coverage authority")

        planned_analyses = {
            item.planned_analysis_id: item for item in projection.planned_analyses
        }
        planned_comparisons = {
            item.planned_comparison_id: item for item in projection.planned_comparisons
        }
        analysis_entries = []
        comparison_entries = []
        result_owners = {}
        comparison_owners = {}
        outcome_statuses = {}

        for outcome_id in manifest.analysis_outcome_ids:
            outcome = self.execution_repository.get_analysis_outcome(
                outcome_id, project_id=project_id
            )
            if outcome is None or outcome.project_id != project_id or outcome.run_id != run_id:
                raise QuantitativeFindingLineageError("RD analysis outcome is unavailable")
            planned = planned_analyses.get(outcome.planned_analysis_id)
            if planned is None or outcome.plan_fingerprint != projection.plan_fingerprint:
                raise QuantitativeFindingLineageError("unplanned RD analysis outcome")
            outcome_statuses[outcome.planned_analysis_id] = outcome.status
            if outcome.status is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS:
                if outcome.artifacts:
                    raise QuantitativeFindingLineageError(
                        "failed, blocked, or skipped RD outcome exposes artifacts"
                    )
                continue
            for artifact in outcome.artifacts:
                if artifact.artifact_type != "STATISTICAL_RESULT":
                    continue
                result = self.state.load(
                    artifact.record_id,
                    project_id=project_id,
                    expected_type=StatisticalResult,
                )
                self._verify_artifact(artifact, result)
                key = (result.result_id, result.reproducibility_fingerprint)
                if key in result_owners:
                    raise QuantitativeFindingLineageError(
                        "ambiguous StatisticalResult RD ownership"
                    )
                entry = DesignAwareAnalysisSupportEntry(
                    result.result_id,
                    result.reproducibility_fingerprint,
                    self._result_projection(result),
                    outcome.outcome_id,
                    outcome.fingerprint,
                    planned.planned_analysis_id,
                    planned.specification.specification_id,
                    planned.specification_fingerprint,
                    planned.objective_ids,
                    planned.research_question_ids,
                    planned.analytical_requirement_ids,
                    planned.obligation,
                    planned.assumptions,
                    tuple(dict.fromkeys(planned.limitations + outcome.limitations)),
                )
                result_owners[key] = entry
                analysis_entries.append(entry)

        for outcome_id in manifest.comparison_outcome_ids:
            outcome = self.execution_repository.get_comparison_outcome(
                outcome_id, project_id=project_id
            )
            if outcome is None or outcome.project_id != project_id or outcome.run_id != run_id:
                raise QuantitativeFindingLineageError("RD comparison outcome is unavailable")
            planned = planned_comparisons.get(outcome.planned_comparison_id)
            if planned is None or outcome.plan_fingerprint != projection.plan_fingerprint:
                raise QuantitativeFindingLineageError("unplanned RD comparison outcome")
            outcome_statuses[outcome.planned_comparison_id] = outcome.status
            if outcome.status is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS:
                if outcome.artifacts:
                    raise QuantitativeFindingLineageError(
                        "failed or blocked RD comparison exposes artifacts"
                    )
                continue
            for artifact in outcome.artifacts:
                if artifact.artifact_type != "COMPARISON_RESULT":
                    continue
                result = self.state.load(
                    artifact.record_id,
                    project_id=project_id,
                    expected_type=AnalyticalComparisonResult,
                )
                self._verify_artifact(artifact, result)
                precursors = (
                    (result.group_a_result_id, result.group_a_result_fingerprint),
                    (result.group_b_result_id, result.group_b_result_fingerprint),
                )
                if any(item not in result_owners for item in precursors):
                    raise QuantitativeFindingLineageError(
                        "ComparisonResult precursor is outside successful RD authority"
                    )
                key = (result.comparison_result_id, result.reproducibility_fingerprint)
                if key in comparison_owners:
                    raise QuantitativeFindingLineageError(
                        "ambiguous ComparisonResult RD ownership"
                    )
                entry = DesignAwareComparisonSupportEntry(
                    result.comparison_result_id,
                    result.reproducibility_fingerprint,
                    self._comparison_projection(result),
                    precursors,
                    outcome.outcome_id,
                    outcome.fingerprint,
                    planned.planned_comparison_id,
                    planned.specification.comparison_id,
                    planned.specification_fingerprint,
                    planned.objective_ids,
                    planned.research_question_ids,
                    planned.analytical_requirement_ids,
                    planned.obligation,
                    planned.assumptions,
                    tuple(dict.fromkeys(planned.limitations + outcome.limitations)),
                )
                comparison_owners[key] = entry
                comparison_entries.append(entry)

        self._require_complete_mandatory(
            projection, outcome_statuses, result_owners, comparison_owners
        )
        analysis_entries = tuple(sorted(analysis_entries, key=lambda item: item.result_id))
        comparison_entries = tuple(
            sorted(comparison_entries, key=lambda item: item.comparison_result_id)
        )
        requirement_ids = tuple(
            sorted(
                {
                    requirement_id
                    for item in projection.planned_analyses + projection.planned_comparisons
                    for requirement_id in item.analytical_requirement_ids
                }
            )
        )
        limitations = tuple(
            dict.fromkeys(
                manifest.limitations
                + tuple(
                    limitation
                    for item in projection.planned_analyses + projection.planned_comparisons
                    for limitation in item.limitations
                )
            )
        )
        payload = {
            "contract": FINDING_LINEAGE_METHOD_VERSION,
            "project": project_id,
            "run": run_id,
            "rd": (manifest.manifest_id, manifest.fingerprint),
            "rd_coverage": (coverage.coverage_id, coverage.fingerprint),
            "rc": (
                projection.plan_id,
                projection.plan_version_id,
                projection.plan_fingerprint,
            ),
            "dataset": (dataset.version_id, dataset.dataset_fingerprint),
            "codebook": (codebook.codebook_version_id, codebook.fingerprint),
            "analyses": tuple(self._analysis_entry_payload(item) for item in analysis_entries),
            "comparisons": tuple(
                self._comparison_entry_payload(item) for item in comparison_entries
            ),
            "requirements": requirement_ids,
            "limitations": limitations,
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        return DesignAwareFindingInputAuthority(
            f"re-input-{fingerprint}",
            project_id,
            run_id,
            manifest.manifest_id,
            manifest.fingerprint,
            coverage.coverage_id,
            coverage.fingerprint,
            projection.plan_id,
            projection.plan_version_id,
            projection.plan_fingerprint,
            dataset.version_id,
            dataset.dataset_fingerprint,
            codebook.codebook_version_id,
            codebook.fingerprint,
            analysis_entries,
            comparison_entries,
            requirement_ids,
            limitations,
            FINDING_LINEAGE_METHOD_VERSION,
            fingerprint,
        )

    def prompt_context(self, authority: DesignAwareFindingInputAuthority):
        return {
            "contract_version": authority.method_version,
            "rd_execution_manifest_id": authority.rd_execution_manifest_id,
            "rd_execution_manifest_fingerprint": authority.rd_execution_manifest_fingerprint,
            "rc_plan_id": authority.rc_plan_id,
            "rc_plan_fingerprint": authority.rc_plan_fingerprint,
            "analysis_lineage": tuple(
                {
                    "result_id": item.result_id,
                    "planned_analysis_id": item.planned_analysis_id,
                    "specification_id": item.specification_id,
                    "objective_ids": item.objective_ids,
                    "research_question_ids": item.research_question_ids,
                    "analytical_requirement_ids": item.analytical_requirement_ids,
                }
                for item in authority.analysis_entries
            ),
            "comparison_lineage": tuple(
                {
                    "comparison_result_id": item.comparison_result_id,
                    "planned_comparison_id": item.planned_comparison_id,
                    "specification_id": item.specification_id,
                    "objective_ids": item.objective_ids,
                    "research_question_ids": item.research_question_ids,
                    "analytical_requirement_ids": item.analytical_requirement_ids,
                }
                for item in authority.comparison_entries
            ),
        }

    def load_results(self, authority: DesignAwareFindingInputAuthority):
        available_results = {
            (item.result_id, item.reproducibility_fingerprint): item
            for item in self.state.list_for_run(
                authority.run_id,
                project_id=authority.project_id,
                expected_type=StatisticalResult,
            )
        }
        available_comparisons = {
            (item.comparison_result_id, item.reproducibility_fingerprint): item
            for item in self.state.list_for_run(
                authority.run_id,
                project_id=authority.project_id,
                expected_type=AnalyticalComparisonResult,
            )
        }
        results = []
        comparisons = []
        for entry in authority.analysis_entries:
            result = available_results.get((entry.result_id, entry.result_fingerprint))
            if result is None:
                raise QuantitativeFindingLineageError("StatisticalResult record is unavailable")
            results.append(result)
        for entry in authority.comparison_entries:
            result = available_comparisons.get(
                (entry.comparison_result_id, entry.comparison_result_fingerprint)
            )
            if result is None:
                raise QuantitativeFindingLineageError("ComparisonResult record is unavailable")
            comparisons.append(result)
        return tuple(results), tuple(comparisons)
    def finalize(
        self,
        *,
        authority,
        generation_record_id,
        generation: QuantitativeFindingGenerationResult,
    ):
        if generation.input_result_bundle_fingerprint != self.expected_generation_bundle_fingerprint(
            authority
        ):
            raise QuantitativeFindingLineageError("Finding generation input authority mismatch")
        analysis = {item.result_id: item for item in authority.analysis_entries}
        comparisons = {
            item.comparison_result_id: item for item in authority.comparison_entries
        }
        entries = []
        for finding in generation.accepted_findings:
            resolved_analysis = []
            resolved_comparisons = []
            for reference in finding.statistical_result_refs:
                item = analysis.get(reference.result_id)
                if item is None or item.result_fingerprint != reference.reproducibility_fingerprint:
                    raise QuantitativeFindingLineageError("Finding references unauthorized RD result")
                resolved_analysis.append(item)
            for reference in finding.comparison_result_refs:
                item = comparisons.get(reference.comparison_result_id)
                if item is None or item.comparison_result_fingerprint != reference.reproducibility_fingerprint:
                    raise QuantitativeFindingLineageError(
                        "Finding references unauthorized RD comparison"
                    )
                resolved_comparisons.append(item)
            payload = {
                "finding": (finding.finding_id, finding.support_validation_fingerprint),
                "analyses": tuple(
                    (item.result_id, item.result_fingerprint, item.rd_outcome_id)
                    for item in resolved_analysis
                ),
                "comparisons": tuple(
                    (
                        item.comparison_result_id,
                        item.comparison_result_fingerprint,
                        item.rd_outcome_id,
                    )
                    for item in resolved_comparisons
                ),
                "version": FINDING_LINEAGE_METHOD_VERSION,
            }
            fingerprint = canonical_digest(payload, digest_provider=self.digest)
            entries.append(
                FindingDesignLineageEntry(
                    finding.finding_id,
                    finding.support_validation_fingerprint,
                    tuple(
                        (item.result_id, item.result_fingerprint)
                        for item in resolved_analysis
                    ),
                    tuple(
                        (
                            item.comparison_result_id,
                            item.comparison_result_fingerprint,
                        )
                        for item in resolved_comparisons
                    ),
                    tuple(
                        sorted(
                            {
                                (item.rd_outcome_id, item.rd_outcome_fingerprint)
                                for item in resolved_analysis + resolved_comparisons
                            }
                        )
                    ),
                    tuple(sorted({item.planned_analysis_id for item in resolved_analysis})),
                    tuple(
                        sorted(
                            {item.planned_comparison_id for item in resolved_comparisons}
                        )
                    ),
                    tuple(
                        sorted(
                            {
                                value
                                for item in resolved_analysis + resolved_comparisons
                                for value in item.objective_ids
                            }
                        )
                    ),
                    tuple(
                        sorted(
                            {
                                value
                                for item in resolved_analysis + resolved_comparisons
                                for value in item.research_question_ids
                            }
                        )
                    ),
                    tuple(
                        sorted(
                            {
                                value
                                for item in resolved_analysis + resolved_comparisons
                                for value in item.analytical_requirement_ids
                            }
                        )
                    ),
                    fingerprint,
                )
            )
        entries = tuple(sorted(entries, key=lambda item: item.finding_id))
        coverage = self._coverage(authority, generation, entries)
        coverage = self.repository.save_coverage(coverage)
        payload = {
            "generation_record": generation_record_id,
            "generation": generation.generation_fingerprint,
            "input": (authority.authority_id, authority.fingerprint),
            "rd": (
                authority.rd_execution_manifest_id,
                authority.rd_execution_manifest_fingerprint,
            ),
            "rc": (authority.rc_plan_id, authority.rc_plan_fingerprint),
            "coverage": (coverage.coverage_id, coverage.fingerprint),
            "entries": tuple(item.fingerprint for item in entries),
            "version": FINDING_LINEAGE_METHOD_VERSION,
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        manifest = QuantitativeFindingDesignLineageManifest(
            f"re-lineage-{fingerprint}",
            authority.project_id,
            authority.run_id,
            generation_record_id,
            generation.generation_fingerprint,
            authority.authority_id,
            authority.fingerprint,
            authority.rd_execution_manifest_id,
            authority.rd_execution_manifest_fingerprint,
            authority.rc_plan_id,
            authority.rc_plan_fingerprint,
            coverage.coverage_id,
            coverage.fingerprint,
            entries,
            FINDING_LINEAGE_METHOD_VERSION,
            fingerprint,
        )
        return self.repository.save_manifest(manifest), coverage

    def expected_generation_bundle_fingerprint(self, authority):
        bundle = {
            "statistical_results": tuple(
                item.safe_numerical_projection for item in authority.analysis_entries
            ),
            "comparison_results": tuple(
                item.safe_comparison_projection for item in authority.comparison_entries
            ),
            "limitations": self.generation_limitations(authority),
        }
        return canonical_digest(bundle, digest_provider=self.digest)

    @staticmethod
    def generation_limitations(authority):
        return authority.limitations + (
            f"DESIGN_AWARE_INPUT_AUTHORITY:{authority.authority_id}:{authority.fingerprint}",
        )
    def dataset_only_absence(self, *, project_id, run_id, generation_record_id, generation):
        payload = {
            "project": project_id,
            "run": run_id,
            "generation": generation.generation_fingerprint,
            "status": "NO_DESIGN_AWARE_FINDING_LINEAGE",
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        value = DatasetOnlyFindingLineageAbsence(
            f"re-absence-{fingerprint}",
            project_id,
            run_id,
            generation_record_id,
            generation.generation_fingerprint,
            "NO_DESIGN_AWARE_FINDING_LINEAGE",
            fingerprint,
        )
        return self.repository.save_dataset_only_absence(value)

    def _preflight(self, project_id, run_id, manifest, projection, dataset, codebook):
        if manifest.project_id != project_id or manifest.run_id != run_id:
            raise QuantitativeFindingLineageError("RD manifest project/run mismatch")
        if manifest.execution_mode is not QuantitativeAnalysisExecutionMode.DESIGN_AWARE_EXECUTION:
            raise QuantitativeFindingLineageError("design-aware QI requires design-aware RD authority")
        if manifest.status not in {
            AnalysisExecutionManifestStatus.COMPLETED,
            AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES,
        }:
            raise QuantitativeFindingLineageError("RD execution is incomplete")
        if (
            manifest.plan_id != projection.plan_id
            or manifest.plan_version_id != projection.plan_version_id
            or manifest.plan_fingerprint != projection.plan_fingerprint
            or manifest.dataset_version_id != dataset.version_id
            or manifest.dataset_fingerprint != dataset.dataset_fingerprint
            or manifest.data_fingerprint != dataset.data_fingerprint
            or manifest.schema_fingerprint != dataset.schema_fingerprint
            or manifest.codebook_version_id != codebook.codebook_version_id
            or manifest.codebook_fingerprint != codebook.fingerprint
            or manifest.quality_assessment_fingerprint
            != projection.quality_assessment_fingerprint
        ):
            raise QuantitativeFindingLineageError("stale RD/RC/Dataset/Codebook/QC authority")

    @staticmethod
    def _require_complete_mandatory(projection, statuses, results, comparisons):
        for item in projection.planned_analyses:
            if item.obligation == "MANDATORY" and (
                statuses.get(item.planned_analysis_id)
                is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS
                or not any(
                    owner.planned_analysis_id == item.planned_analysis_id
                    for owner in results.values()
                )
            ):
                raise QuantitativeFindingLineageError(
                    "mandatory RD analysis is incomplete"
                )
        for item in projection.planned_comparisons:
            if item.obligation == "MANDATORY" and (
                statuses.get(item.planned_comparison_id)
                is not AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS
                or not any(
                    owner.planned_comparison_id == item.planned_comparison_id
                    for owner in comparisons.values()
                )
            ):
                raise QuantitativeFindingLineageError(
                    "mandatory RD comparison is incomplete"
                )

    @staticmethod
    def _verify_artifact(artifact, value):
        if authority_fingerprint(value) != artifact.authority_fingerprint:
            raise QuantitativeFindingLineageError("RD artifact fingerprint mismatch")

    @staticmethod
    def _result_projection(item):
        return {
            "result_id": item.result_id,
            "reproducibility_fingerprint": item.reproducibility_fingerprint,
            "display_label": item.statistic_type,
            "variable_id": item.variable_id,
            "statistic_type": item.statistic_type,
            "value": canonical_scalar(item.value),
            "display_value_1dp": QuantitativeFindingSupportValidator.display_value(
                Decimal(str(item.value)), decimal_places=1
            ),
            "denominator": canonical_scalar(item.denominator),
            "category_value": canonical_scalar(item.category_value),
            "row_category_value": canonical_scalar(item.row_category_value),
            "column_category_value": canonical_scalar(item.column_category_value),
            "filter_definition": item.filter_definition,
            "base_definition": item.base_definition,
            "weighting_status": item.weighting_status,
            "weight_set_fingerprint": item.weight_set_fingerprint,
            "unweighted_n": item.unweighted_n,
            "weighted_base": canonical_scalar(item.weighted_base),
            "missing_value_semantics": item.missing_value_semantics,
            "presentation_eligible": item.presentation_eligible,
        }

    @staticmethod
    def _comparison_projection(item):
        return {
            "comparison_result_id": item.comparison_result_id,
            "reproducibility_fingerprint": item.reproducibility_fingerprint,
            "group_a_result_id": item.group_a_result_id,
            "group_b_result_id": item.group_b_result_id,
            "observed_difference": canonical_scalar(item.observed_difference),
            "p_value": canonical_scalar(item.p_value),
            "alpha": canonical_scalar(item.alpha),
            "significant": item.significant,
            "supports_significance_wording": item.supports_significance_wording,
            "method": item.method,
            "method_version": item.method_version,
            "group_a_base": item.group_a_base,
            "group_b_base": item.group_b_base,
        }

    @staticmethod
    def _analysis_entry_payload(item):
        return (
            item.result_id,
            item.result_fingerprint,
            item.rd_outcome_id,
            item.rd_outcome_fingerprint,
            item.planned_analysis_id,
            item.specification_id,
            item.specification_fingerprint,
            item.objective_ids,
            item.research_question_ids,
            item.analytical_requirement_ids,
            item.obligation,
            item.assumptions,
            item.limitations,
            item.safe_numerical_projection,
        )

    @staticmethod
    def _comparison_entry_payload(item):
        return (
            item.comparison_result_id,
            item.comparison_result_fingerprint,
            item.precursor_result_ids_and_fingerprints,
            item.rd_outcome_id,
            item.rd_outcome_fingerprint,
            item.planned_comparison_id,
            item.specification_id,
            item.specification_fingerprint,
            item.objective_ids,
            item.research_question_ids,
            item.analytical_requirement_ids,
            item.obligation,
            item.assumptions,
            item.limitations,
            item.safe_comparison_projection,
        )

    def _coverage(self, authority, generation, lineage_entries):
        by_requirement = {item: [] for item in authority.analytical_requirement_ids}
        outcomes = {item: set() for item in authority.analytical_requirement_ids}
        for entry in lineage_entries:
            for requirement_id in entry.analytical_requirement_ids:
                by_requirement.setdefault(requirement_id, []).append(entry.finding_id)
                outcomes.setdefault(requirement_id, set()).update(
                    item[0] for item in entry.rd_outcome_ids_and_fingerprints
                )
        supported_requirements = {
            requirement
            for item in authority.analysis_entries + authority.comparison_entries
            for requirement in item.analytical_requirement_ids
        }
        entries = []
        for requirement_id in authority.analytical_requirement_ids:
            findings = tuple(sorted(set(by_requirement.get(requirement_id, ()))))
            if findings:
                status = FindingCoverageStatus.FINDING_SUPPORTED
                rationale = "One or more QH-supported Findings use authorized executed evidence."
            elif requirement_id not in supported_requirements:
                status = FindingCoverageStatus.BLOCKED_NO_EXECUTED_RESULT
                rationale = "No successful RD result is available for this requirement."
            elif generation.acceptance_summary.get("proposed", 0) == 0:
                status = FindingCoverageStatus.NO_FINDING_PROPOSED
                rationale = "QI produced no Finding proposal for available evidence."
            else:
                status = FindingCoverageStatus.PROPOSALS_REJECTED_UNSUPPORTED
                rationale = "No proposal for available evidence passed QH authority."
            entries.append(
                FindingCoverageEntry(
                    requirement_id,
                    status,
                    findings,
                    tuple(sorted(outcomes.get(requirement_id, set()))),
                    rationale,
                )
            )
        payload = {
            "input": (authority.authority_id, authority.fingerprint),
            "generation": generation.generation_fingerprint,
            "entries": tuple(
                (item.analytical_requirement_id, item.status.value, item.finding_ids, item.rd_outcome_ids)
                for item in entries
            ),
            "version": FINDING_LINEAGE_METHOD_VERSION,
        }
        fingerprint = canonical_digest(payload, digest_provider=self.digest)
        return QuantitativeFindingCoverageManifest(
            f"re-coverage-{fingerprint}",
            authority.project_id,
            authority.run_id,
            authority.authority_id,
            authority.fingerprint,
            generation.generation_fingerprint,
            tuple(entries),
            FINDING_LINEAGE_METHOD_VERSION,
            fingerprint,
        )
