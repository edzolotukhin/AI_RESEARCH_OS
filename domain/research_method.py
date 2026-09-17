from __future__ import annotations

DESK = "DESK"
QUANTITATIVE = "QUANTITATIVE"

SUPPORTED_RESEARCH_METHODS = (DESK, QUANTITATIVE)


def canonicalize_research_methods(
    values: object,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if values is None:
        if allow_empty:
            return ()
        raise ValueError("At least one research method is required")
    if isinstance(values, str):
        raw = (values,)
    else:
        raw = tuple(values)  # type: ignore[arg-type]
    normalized = tuple(str(value).strip().upper() for value in raw)
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate research method")
    unsupported = set(normalized) - set(SUPPORTED_RESEARCH_METHODS)
    if unsupported:
        raise ValueError(f"Unsupported research method: {sorted(unsupported)[0]}")
    ordered = tuple(item for item in SUPPORTED_RESEARCH_METHODS if item in normalized)
    if not ordered and not allow_empty:
        raise ValueError("At least one research method is required")
    return ordered
