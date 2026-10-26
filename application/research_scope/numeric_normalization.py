from __future__ import annotations

from decimal import Decimal, InvalidOperation


GROUPING_SPACES = " \u00a0\u202f"
PERCENT_UNITS = frozenset({"%", "percent", "percentage", "відсоток", "відсотки", "відсотків"})


def normalize_numeric_value(value: object) -> str:
    """Return a scale-preserving decimal token; never infer a unit or scale."""
    token = str(value).strip().rstrip("%").strip()
    for separator in GROUPING_SPACES:
        token = token.replace(separator, "")
    token = token.replace(",", ".")
    try:
        number = Decimal(token)
    except InvalidOperation:
        return token
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", ""} else normalized


def normalize_numeric_unit(value: object) -> str:
    token = " ".join(str(value).casefold().split())
    return "%" if token in PERCENT_UNITS else token.replace(" ", "_")


def numeric_token_authority(token: str) -> tuple[str, str | None]:
    """Return normalized value and only the unit explicitly present in prose."""
    stripped = token.strip()
    return normalize_numeric_value(stripped), "%" if stripped.endswith("%") else None


def numeric_authority_matches(*, token: str, authority_value: str, authority_unit: str) -> bool:
    value, explicit_unit = numeric_token_authority(token)
    allowed_value = normalize_numeric_value(authority_value)
    allowed_unit = normalize_numeric_unit(authority_unit)
    if value != allowed_value:
        return False
    if explicit_unit is not None:
        return allowed_unit == explicit_unit
    return allowed_unit != "%"
