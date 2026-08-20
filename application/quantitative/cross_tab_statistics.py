from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.fingerprints import (
    canonical_digest,
    canonical_scalar,
    fingerprint_analysis_specification,
    fingerprint_statistical_result_payload,
)
from application.quantitative.one_way_statistics import QuantitativeAnalysisError, _is_missing
from domain.quantitative.analysis import (
    CrossTabAnalysisSpecification,
    StatisticalResult,
    StatisticalTable,
)
from domain.quantitative.dataset import (
    CodebookVersion,
    DatasetVersion,
    PiiClassification,
    VariableDefinition,
    VariableRole,
    VariableType,
)
from domain.quantitative.weighting import (
    AnalyticalDatasetView,
    WeightSet,
    WeightValidationStatus,
    WeightingMode,
)


COMPUTATION_METHOD = "deterministic_cross_tab_column_percentage"
COMPUTATION_VERSION = "qd-1"
_CATEGORICAL_TYPES = {
    VariableType.CATEGORICAL,
    VariableType.ORDINAL_SCALE,
    VariableType.DEMOGRAPHIC,
}


class CrossTabStatisticsService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def eligible_respondent_refs(
        self,
        *,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
        specification: CrossTabAnalysisSpecification,
    ) -> tuple[str, ...]:
        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        if len(rows) != len(refs):
            raise QuantitativeAnalysisError("respondent lineage does not match dataset rows")
        filter_variable = self._validate_filter(codebook, specification, rows)
        if filter_variable is None:
            return tuple(refs)
        index = self._index(codebook, filter_variable.variable_id)
        return tuple(
            ref
            for row, ref in zip(rows, refs)
            if not _is_missing(row[index], filter_variable.missing_rules)
            and self._key(row[index]) == self._key(specification.filter_category_value)
        )

    def compute(
        self,
        *,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
        specification: CrossTabAnalysisSpecification,
        view: AnalyticalDatasetView,
        weight_set: WeightSet | None = None,
    ) -> tuple[StatisticalTable, tuple[StatisticalResult, ...]]:
        if not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
            raise QuantitativeAnalysisError("approved codebook must match dataset")
        row_variable = codebook.variable_by_id(specification.variable_id)
        column_variable = codebook.variable_by_id(specification.column_variable_id)
        self._validate_dimension(row_variable)
        self._validate_dimension(column_variable)
        if row_variable.variable_id == column_variable.variable_id:
            raise QuantitativeAnalysisError("cross-tab dimensions must be distinct")
        if specification.percentage_orientation != "COLUMN":
            raise QuantitativeAnalysisError("V1 cross-tabs support COLUMN percentages only")

        spec_fp = fingerprint_analysis_specification(specification, digest_provider=self._digest)
        resolved_spec = replace(specification, fingerprint=spec_fp)
        if (
            view.dataset_version_id != dataset.version_id
            or view.dataset_fingerprint != dataset.dataset_fingerprint
            or view.analysis_specification_fingerprint != spec_fp
        ):
            raise QuantitativeAnalysisError("analytical view is stale or belongs to another specification")

        weighted = specification.weighting_status == "WEIGHTED"
        if weighted:
            if (
                view.weighting_mode is not WeightingMode.WEIGHTED
                or weight_set is None
                or weight_set.validation_status is WeightValidationStatus.BLOCKED
                or weight_set.dataset_version_id != dataset.version_id
                or weight_set.dataset_fingerprint != dataset.dataset_fingerprint
                or view.weight_set_id != weight_set.weight_set_id
                or view.weight_set_fingerprint != weight_set.reproducibility_fingerprint
            ):
                raise QuantitativeAnalysisError("weighted cross-tab requires a current valid WeightSet view")
        elif specification.weighting_status == "UNWEIGHTED":
            if view.weighting_mode is not WeightingMode.UNWEIGHTED or weight_set is not None or view.weight_set_id is not None:
                raise QuantitativeAnalysisError("unweighted cross-tab cannot carry a WeightSet")
        else:
            raise QuantitativeAnalysisError("unsupported weighting status")

        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        filter_variable = self._validate_filter(codebook, specification, rows)
        eligible_refs = self.eligible_respondent_refs(dataset=dataset, codebook=codebook, specification=specification)
        expected_eligible_fp = canonical_digest(tuple(sorted(eligible_refs)), digest_provider=self._digest)
        if view.eligible_respondent_set_fingerprint != expected_eligible_fp:
            raise QuantitativeAnalysisError("analytical view respondent set does not match filter")
        eligible = set(eligible_refs)
        weights = dict(weight_set.weight_vector) if weight_set else {}
        if weighted and set(refs) != set(weights):
            raise QuantitativeAnalysisError("WeightSet does not cover retained respondents")

        row_index = self._index(codebook, row_variable.variable_id)
        column_index = self._index(codebook, column_variable.variable_id)
        records = tuple(
            (row[row_index], row[column_index], weights[ref] if weighted else Decimal(1))
            for row, ref in zip(rows, refs)
            if ref in eligible
        )
        row_missing = tuple(item for item in records if _is_missing(item[0], row_variable.missing_rules))
        column_missing = tuple(item for item in records if _is_missing(item[1], column_variable.missing_rules))
        joint_valid = tuple(
            item
            for item in records
            if not _is_missing(item[0], row_variable.missing_rules)
            and not _is_missing(item[1], column_variable.missing_rules)
        )
        row_values = self._resolved_categories(joint_valid, 0, specification.row_categories, "row")
        column_values = self._resolved_categories(joint_valid, 1, specification.column_categories, "column")

        results: list[StatisticalResult] = []
        total_n = len(joint_valid)
        total_weight = sum((item[2] for item in joint_valid), Decimal(0))
        if weighted and joint_valid and total_weight <= 0:
            raise QuantitativeAnalysisError("weighted total valid base must be positive")
        results.extend(
            (
                self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_TOTAL_VALID_BASE", total_weight if weighted else total_n, None, None, None, total_n, total_weight if weighted else None),
                self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_ROW_MISSING_N", len(row_missing), None, None, None, len(row_missing), sum((item[2] for item in row_missing), Decimal(0)) if weighted else None),
                self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_COLUMN_MISSING_N", len(column_missing), None, None, None, len(column_missing), sum((item[2] for item in column_missing), Decimal(0)) if weighted else None),
            )
        )

        for row_value in row_values:
            matching = tuple(item for item in joint_valid if self._key(item[0]) == self._key(row_value))
            row_n = len(matching)
            row_weight = sum((item[2] for item in matching), Decimal(0))
            results.append(self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_ROW_BASE", row_weight if weighted else row_n, None, row_value, None, row_n, row_weight if weighted else None))

        for column_value in column_values:
            column_records = tuple(item for item in joint_valid if self._key(item[1]) == self._key(column_value))
            column_n = len(column_records)
            column_weight = sum((item[2] for item in column_records), Decimal(0))
            if weighted and column_records and column_weight <= 0:
                raise QuantitativeAnalysisError("weighted column base must be positive")
            denominator = column_weight if weighted else Decimal(column_n)
            results.append(self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_COLUMN_BASE", column_weight if weighted else column_n, None, None, column_value, column_n, column_weight if weighted else None))
            for row_value in row_values:
                cell = tuple(item for item in column_records if self._key(item[0]) == self._key(row_value))
                cell_n = len(cell)
                cell_weight = sum((item[2] for item in cell), Decimal(0))
                results.append(self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_CELL_N", cell_n, column_n, row_value, column_value, cell_n, cell_weight if weighted else None))
                if weighted:
                    results.append(self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_CELL_WEIGHTED_BASE", cell_weight, column_weight, row_value, column_value, cell_n, cell_weight))
                with localcontext() as context:
                    context.prec = 28
                    percentage = cell_weight * Decimal(100) / denominator if denominator else Decimal(0)
                results.append(self._result(dataset, row_variable, column_variable, filter_variable, resolved_spec, view, weight_set, "CROSS_TAB_COLUMN_PERCENTAGE", percentage, column_weight if weighted else column_n, row_value, column_value, cell_n, cell_weight if weighted else None, percentage > specification.presentation_threshold_percent))

        table = self._table(dataset, row_variable, column_variable, resolved_spec, view, weight_set, tuple(results), row_values, column_values)
        return table, tuple(results)

    def _validate_filter(self, codebook, specification, rows):
        if specification.filter_variable_id is None:
            if specification.filter_category_value is not None or specification.filter_definition != "ALL_ROWS":
                raise QuantitativeAnalysisError("invalid categorical filter")
            return None
        variable = codebook.variable_by_id(specification.filter_variable_id)
        self._validate_dimension(variable)
        if specification.filter_category_value is None:
            raise QuantitativeAnalysisError("categorical filter requires a category")
        expected = self.filter_definition(variable.variable_id, specification.filter_category_value)
        if specification.filter_definition != expected:
            raise QuantitativeAnalysisError("filter definition does not match categorical filter")
        index = self._index(codebook, variable.variable_id)
        observed = {self._key(row[index]) for row in rows if not _is_missing(row[index], variable.missing_rules)}
        if self._key(specification.filter_category_value) not in observed:
            raise QuantitativeAnalysisError("unknown filter category")
        return variable

    @staticmethod
    def filter_definition(variable_id: str, category_value: Any) -> str:
        scalar = canonical_scalar(category_value)
        return f"CATEGORY_EQUALS:{variable_id}:{scalar['type']}:{scalar['value']}"

    @staticmethod
    def _validate_dimension(variable: VariableDefinition) -> None:
        if (
            not variable.analytically_eligible
            or variable.variable_type not in _CATEGORICAL_TYPES
            or variable.role in {VariableRole.TECHNICAL_ID, VariableRole.PII, VariableRole.WEIGHT}
            or variable.pii_classification is not PiiClassification.NONE
            or variable.multiple_response_set is not None
        ):
            raise QuantitativeAnalysisError("cross-tab dimension is not an eligible single-response categorical variable")

    @staticmethod
    def _index(codebook: CodebookVersion, variable_id: str) -> int:
        return next(index for index, item in enumerate(codebook.variables) if item.variable_id == variable_id)

    @staticmethod
    def _key(value: Any) -> tuple[str, str]:
        scalar = canonical_scalar(value)
        return scalar["type"], scalar["value"]

    def _resolved_categories(self, records, position, requested, label):
        observed: dict[tuple[str, str], Any] = {}
        for record in records:
            observed.setdefault(self._key(record[position]), record[position])
        if requested:
            unknown = [item for item in requested if self._key(item) not in observed]
            if unknown:
                raise QuantitativeAnalysisError(f"unknown {label} category")
            omitted = set(observed) - {self._key(item) for item in requested}
            if omitted:
                raise QuantitativeAnalysisError(f"{label} category definition omits observed categories")
            return tuple(requested)
        return tuple(observed[key] for key in sorted(observed))

    @staticmethod
    def _missing_payload(*variables: VariableDefinition) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "variable_id": variable.variable_id,
                "variable_fingerprint": variable.fingerprint,
                "rules": tuple(
                    {
                        "kind": rule.kind,
                        "value": canonical_scalar(rule.value),
                        "low": canonical_scalar(rule.low),
                        "high": canonical_scalar(rule.high),
                        "source": rule.source,
                    }
                    for rule in variable.missing_rules
                ),
            }
            for variable in variables
        )

    def _result(self, dataset, row_variable, column_variable, filter_variable, spec, view, weight_set, statistic_type, value, denominator, row_category, column_category, unweighted_n, weighted_base, presentation_eligible=True):
        missing = self._missing_payload(row_variable, column_variable, *((filter_variable,) if filter_variable else ()))
        payload = {
            "dataset_version_id": dataset.version_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "data_fingerprint": dataset.data_fingerprint,
            "codebook_fingerprint": dataset.codebook_fingerprint,
            "analysis_specification_id": spec.specification_id,
            "analysis_specification_fingerprint": spec.fingerprint,
            "row_variable_id": row_variable.variable_id,
            "row_variable_fingerprint": row_variable.fingerprint,
            "row_category": canonical_scalar(row_category),
            "column_variable_id": column_variable.variable_id,
            "column_variable_fingerprint": column_variable.fingerprint,
            "column_category": canonical_scalar(column_category),
            "filter_definition": spec.filter_definition,
            "base_definition": spec.base_definition,
            "missing_value_semantics": missing,
            "weighting_status": spec.weighting_status,
            "weight_set_fingerprint": weight_set.reproducibility_fingerprint if weight_set else None,
            "analytical_view_fingerprint": view.fingerprint,
            "unweighted_n": unweighted_n,
            "weighted_base": canonical_scalar(weighted_base),
            "statistic_type": statistic_type,
            "value": canonical_scalar(value),
            "denominator": canonical_scalar(denominator),
            "percentage_orientation": "COLUMN",
            "computation_method": COMPUTATION_METHOD,
            "computation_version": COMPUTATION_VERSION,
            "presentation_eligible": presentation_eligible,
        }
        fingerprint = fingerprint_statistical_result_payload(payload, digest_provider=self._digest)
        return StatisticalResult(
            result_id=str(uuid5(NAMESPACE_URL, f"qd-statistical-result:{fingerprint}")), dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint, data_fingerprint=dataset.data_fingerprint,
            codebook_fingerprint=dataset.codebook_fingerprint, variable_id=row_variable.variable_id,
            variable_fingerprint=row_variable.fingerprint, analysis_specification_id=spec.specification_id,
            analysis_specification_fingerprint=spec.fingerprint, weighting_status=spec.weighting_status,
            filter_definition=spec.filter_definition, base_definition=spec.base_definition,
            missing_value_semantics=missing, statistic_type=statistic_type, value=value,
            denominator=denominator, category_value=row_category, computation_method=COMPUTATION_METHOD,
            computation_version=COMPUTATION_VERSION, presentation_eligible=presentation_eligible,
            reproducibility_fingerprint=fingerprint, weight_set_id=weight_set.weight_set_id if weight_set else None,
            weight_set_fingerprint=weight_set.reproducibility_fingerprint if weight_set else None,
            analytical_view_id=view.view_id, analytical_view_fingerprint=view.fingerprint,
            unweighted_n=unweighted_n, weighted_base=weighted_base,
            row_variable_id=row_variable.variable_id, row_variable_fingerprint=row_variable.fingerprint,
            row_category_value=row_category, column_variable_id=column_variable.variable_id,
            column_variable_fingerprint=column_variable.fingerprint, column_category_value=column_category,
            percentage_orientation="COLUMN",
        )

    def _table(self, dataset, row_variable, column_variable, spec, view, weight_set, results, row_values, column_values):
        result_ids = tuple(item.result_id for item in results)
        payload = {
            "dataset": dataset.dataset_fingerprint, "specification": spec.fingerprint,
            "row": row_variable.fingerprint, "column": column_variable.fingerprint,
            "orientation": "COLUMN", "weight_set": weight_set.reproducibility_fingerprint if weight_set else None,
            "view": view.fingerprint, "results": result_ids,
        }
        fingerprint = canonical_digest(payload, digest_provider=self._digest)
        row_labels = self._labels(row_variable, row_values)
        column_labels = self._labels(column_variable, column_values)
        return StatisticalTable(
            table_id=str(uuid5(NAMESPACE_URL, f"qd-statistical-table:{fingerprint}")),
            analysis_specification_id=spec.specification_id,
            analysis_specification_fingerprint=spec.fingerprint,
            row_variable_id=row_variable.variable_id, column_variable_id=column_variable.variable_id,
            percentage_orientation="COLUMN", weighting_status=spec.weighting_status,
            weight_set_fingerprint=weight_set.reproducibility_fingerprint if weight_set else None,
            analytical_view_fingerprint=view.fingerprint, filter_definition=spec.filter_definition,
            base_definition=spec.base_definition, ordered_result_ids=result_ids,
            row_labels=row_labels, column_labels=column_labels, fingerprint=fingerprint,
        )

    def _labels(self, variable, values):
        imported = {self._key(value): label for value, label in variable.value_labels}
        return tuple((f"{self._key(value)[0]}:{self._key(value)[1]}", imported.get(self._key(value), str(value))) for value in values)
