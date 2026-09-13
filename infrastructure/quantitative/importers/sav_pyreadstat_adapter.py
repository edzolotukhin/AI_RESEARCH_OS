from __future__ import annotations

import io
import math
from typing import Any

import pyreadstat

from application.ports.quantitative_dataset_ports import ParsedDataset, ParsedVariable
from domain.quantitative.dataset import DatasetFormat


class SavPyreadstatAdapter:
    format = DatasetFormat.SAV

    def parse(
        self,
        data: bytes,
        *,
        filename: str,
        data_sheet: str | None = None,
    ) -> ParsedDataset:
        if data_sheet is not None:
            raise ValueError("SAV import does not accept data_sheet")
        columns, metadata = pyreadstat.read_sav(
            io.BytesIO(data),
            output_format="dict",
            apply_value_formats=False,
            user_missing=True,
        )
        names = tuple(metadata.column_names)
        labels_by_name = dict(metadata.column_names_to_labels or {})
        value_labels = dict(metadata.variable_value_labels or {})
        missing_ranges = dict(metadata.missing_ranges or {})
        measures = dict(metadata.variable_measure or {})
        storage = dict(metadata.readstat_variable_types or {})
        mr_by_variable = _mr_sets_by_variable(getattr(metadata, "mr_sets", None) or {})
        warnings: list[str] = []
        variables: list[ParsedVariable] = []
        for name in names:
            canonical_labels, label_warnings = _canonical_value_labels(
                name, value_labels.get(name) or {},
            )
            canonical_missing, missing_warnings = _canonical_user_missing(
                name, missing_ranges.get(name, ()),
            )
            warnings.extend(label_warnings)
            warnings.extend(missing_warnings)
            variables.append(ParsedVariable(
                name=name,
                label=str(labels_by_name.get(name) or ""),
                storage_type=str(storage.get(name) or "unknown"),
                measurement_level=str(measures.get(name) or "unknown"),
                value_labels=canonical_labels,
                user_missing=canonical_missing,
                metadata={"multiple_response_sets": mr_by_variable.get(name, ())},
            ))
        row_count = len(next(iter(columns.values()), ()))
        rows = tuple(
            tuple(_plain_value(columns[name][row_index]) for name in names)
            for row_index in range(row_count)
        )
        if getattr(metadata, "mr_sets", None):
            warnings.append("sav_multiple_response_metadata_preserved_but_not_executable")
        return ParsedDataset(
            format=DatasetFormat.SAV,
            variables=tuple(variables),
            rows=rows,
            parser_name="pyreadstat",
            parser_version=pyreadstat.__version__,
            warnings=tuple(warnings),
        )


def _mr_sets_by_variable(mr_sets: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for set_name, definition in sorted(mr_sets.items()):
        if not isinstance(definition, dict):
            continue
        variables = definition.get("variable_list") or definition.get("variables") or ()
        for variable in variables:
            result.setdefault(str(variable), []).append(str(set_name))
    return {name: tuple(sorted(values)) for name, values in result.items()}


def _canonical_value_labels(
    variable_name: str,
    labels: dict[Any, Any],
) -> tuple[tuple[tuple[Any, str], ...], tuple[str, ...]]:
    canonical: list[tuple[Any, str]] = []
    warnings: list[str] = []
    for value, label in labels.items():
        plain = _plain_value(value)
        if _is_non_finite(plain):
            warnings.append(
                f"sav_nonfinite_value_label_excluded:{variable_name}:{_non_finite_kind(plain)}"
            )
            continue
        canonical.append((plain, str(label)))
    try:
        ordered = tuple(sorted(canonical))
    except TypeError as exc:
        raise ValueError(
            f"SAV value-label keys are not canonically orderable for {variable_name}"
        ) from exc
    return ordered, tuple(sorted(warnings))


def _canonical_user_missing(
    variable_name: str,
    items: Any,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    canonical: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in items:
        normalized = _normalize_missing(item)
        non_finite = tuple(
            _non_finite_kind(value)
            for value in normalized.values()
            if _is_non_finite(value)
        )
        if non_finite:
            warnings.append(
                f"sav_nonfinite_missing_metadata_excluded:{variable_name}:{','.join(non_finite)}"
            )
            continue
        canonical.append(normalized)
    return tuple(canonical), tuple(sorted(warnings))


def _normalize_missing(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        if "lo" in item or "hi" in item:
            return {"lo": _plain_value(item.get("lo")), "hi": _plain_value(item.get("hi"))}
    return {"value": _plain_value(item)}


def _plain_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return value


def _is_non_finite(value: Any) -> bool:
    return isinstance(value, float) and not math.isfinite(value)


def _non_finite_kind(value: float) -> str:
    if math.isnan(value):
        return "NAN"
    return "POSITIVE_INFINITY" if value > 0 else "NEGATIVE_INFINITY"
