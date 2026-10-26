from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


GROUPING_SPACES = " \u00a0\u202f"
PERCENT_UNITS = frozenset({"%", "percent", "percentage", "відсоток", "відсотки", "відсотків"})
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_CLAUSE_BOUNDARY = re.compile(r"(?<!\d)[,;](?!\d)|[.!?](?=\s|$)")
_RENDERED_NUMBER = re.compile(
    rf"(?<![\w-])(?P<sign>[+-])?\s*(?P<prefix>[$€])?\s*"
    rf"(?P<value>(?:\d{{1,3}}[{GROUPING_SPACES}]\d{{3}}(?:[{GROUPING_SPACES}]\d{{3}})*|\d+)(?:[.,]\d+)?)\s*"
    r"(?P<scale>m|million|млн|млрд)?\s*"
    r"(?P<unit>%|percentage points?|відсот(?:ок|ки|ків)?|грн|uah|usd|руб|per\s+hour|на\s+годину)?"
    r"(?![\w-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RenderedFact:
    raw: str
    value: str | None
    unit: str | None
    scale: str | None
    periods: tuple[str, ...]
    direction: str | None


def rendered_facts(text: str) -> tuple[RenderedFact, ...]:
    """Parse bounded, explicit numeric authority from one factual prose unit."""
    year_matches = tuple(_YEAR.finditer(text))
    years = tuple(dict.fromkeys(match.group(0) for match in year_matches))
    numeric_matches = tuple(
        match for match in _RENDERED_NUMBER.finditer(text)
        if not (
            match.group("value") in years
            and not any((match.group("prefix"), match.group("scale"), match.group("unit")))
        )
    )
    facts: list[RenderedFact] = []
    bound_years: set[str] = set()
    for match in numeric_matches:
        raw_value = match.group("value")
        midpoint = (match.start() + match.end()) / 2
        clause_start, clause_end = _clause_span(text, match.start(), match.end())
        clause_years = tuple(
            year for year in year_matches
            if clause_start <= year.start() and year.end() <= clause_end
        )
        candidate_years = clause_years or year_matches
        periods = tuple(dict.fromkeys(
            year.group(0) for year in candidate_years
            if abs(((year.start() + year.end()) / 2) - midpoint) <= 80
            and abs(((year.start() + year.end()) / 2) - midpoint) == min(
                abs(((year.start() + year.end()) / 2) - ((candidate.start() + candidate.end()) / 2))
                for candidate in numeric_matches
                if clause_start <= candidate.start() and candidate.end() <= clause_end
            )
        ))
        bound_years.update(periods)
        prefix, raw_scale, raw_unit = match.group("prefix") or "", match.group("scale") or "", match.group("unit") or ""
        explicit_unit = normalize_numeric_unit(f"{prefix}{raw_unit}") if prefix or raw_unit else None
        scale = normalize_numeric_unit(raw_scale) if raw_scale else None
        sign = match.group("sign")
        facts.append(RenderedFact(
            raw=match.group(0).strip(), value=normalize_numeric_value(raw_value),
            unit=explicit_unit, scale=scale, periods=periods,
            direction="increase" if sign == "+" else "decrease" if sign == "-" else None,
        ))
    facts.extend(
        RenderedFact(raw=year, value=None, unit=None, scale=None, periods=(year,), direction=None)
        for year in years if year not in bound_years
    )
    return tuple(facts)


def _clause_span(text: str, start: int, end: int) -> tuple[int, int]:
    boundaries = tuple(_CLAUSE_BOUNDARY.finditer(text))
    left = max((item.end() for item in boundaries if item.end() <= start), default=0)
    right = min((item.start() for item in boundaries if item.start() >= end), default=len(text))
    return left, right


def rendered_fact_matches_numeric_fact(rendered: RenderedFact, authority: Any) -> tuple[bool, tuple[str, ...]]:
    """Match every explicit rendered dimension against one indivisible NumericFact."""
    mismatches: list[str] = []
    if rendered.value is not None:
        if normalize_numeric_value(getattr(authority, "value", "")) != rendered.value:
            mismatches.append("value")
        allowed_unit = normalize_numeric_unit(getattr(authority, "unit", ""))
        if rendered.unit is None:
            if allowed_unit == "%":
                mismatches.append("unit")
        elif allowed_unit != rendered.unit:
            mismatches.append("unit")
        if rendered.scale is not None:
            allowed_scale = normalize_numeric_unit(getattr(authority, "scale", ""))
            # Historical extracted facts stored a lone scale token as the unit.
            legacy_scale_unit = rendered.unit is None and allowed_unit == rendered.scale and allowed_scale == "absolute"
            if allowed_scale != rendered.scale and not legacy_scale_unit:
                mismatches.append("scale")
    if rendered.periods and not set(rendered.periods) <= set(getattr(authority, "periods", ())):
        mismatches.append("period")
    return not mismatches, tuple(mismatches)


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
