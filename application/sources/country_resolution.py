from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet


class CountryResolutionStatus(str, Enum):
    SUPPORTED_COUNTRY = "supported_country"
    UNSUPPORTED_OR_UNRESOLVED = "unsupported_or_unresolved"
    AMBIGUOUS_OR_MULTI_COUNTRY = "ambiguous_or_multi_country"
    NO_COUNTRY = "no_country"


@dataclass(frozen=True)
class CountryResolution:
    status: CountryResolutionStatus
    country: str | None = None


_NO_COUNTRY_GEOGRAPHIES = frozenset(
    {
        "global",
        "globally",
        "world",
        "worldwide",
        "international",
    },
)


def resolve_supported_country(
    geography: str | None,
    *,
    supported_countries: AbstractSet[str],
) -> CountryResolution:
    """Resolve one explicit supported country from structured geography.

    The function deliberately does not inspect query/category text, guess from a
    city, translate, geocode, or map a region to one of its member countries.
    Provider capabilities are supplied by the adapter at the boundary.
    """

    normalized = _normalize(geography or "")
    if not normalized or normalized in _NO_COUNTRY_GEOGRAPHIES:
        return CountryResolution(CountryResolutionStatus.NO_COUNTRY)

    matches = tuple(
        country
        for country in sorted(supported_countries, key=lambda value: (-len(value), value))
        if re.search(rf"(?<![a-z]){re.escape(country)}(?![a-z])", normalized)
    )
    # Avoid counting a shorter supported name nested inside a longer match.
    maximal = tuple(
        country
        for country in matches
        if not any(country != other and country in other for other in matches)
    )
    if len(maximal) == 1:
        return CountryResolution(
            CountryResolutionStatus.SUPPORTED_COUNTRY,
            maximal[0],
        )
    if len(maximal) > 1:
        return CountryResolution(CountryResolutionStatus.AMBIGUOUS_OR_MULTI_COUNTRY)
    return CountryResolution(CountryResolutionStatus.UNSUPPORTED_OR_UNRESOLVED)


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z]+", " ", value.casefold()).split())
