"""Bounded parser for the World Bank indicator API response shape only."""
from __future__ import annotations

import math
import re
from typing import Any

from application.structured_output.json_validator import JsonValidator

MAX_JSON_BYTES = 64_000
MAX_RECORDS = 20
MAX_JSON_DEPTH = 5
WORLD_BANK_HOST = "api.worldbank.org"


def _depth(value: Any, current: int = 0) -> int:
    if current > MAX_JSON_DEPTH:
        return current
    if isinstance(value, dict):
        return max((_depth(v, current + 1) for v in value.values()), default=current)
    if isinstance(value, list):
        return max((_depth(v, current + 1) for v in value), default=current)
    return current


def parse_world_bank_population_json(data: bytes, *, url: str) -> dict[str, Any]:
    """Return structured rows only for ``country/UKR/indicator/SP.POP.TOTL``.

    The caller performs URL safety and redirect validation. This parser adds a
    second host/path/schema guard and never accepts a generic JSON document.
    """
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("world_bank_json_body_limit")

    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if parsed.hostname != WORLD_BANK_HOST or not re.search(
        r"/v2/country/UKR/indicator/SP\.POP\.TOTL(?:/|\?|$)",
        parsed.path + ("?" + parsed.query if parsed.query else ""),
    ):
        raise ValueError("world_bank_json_endpoint_mismatch")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("world_bank_json_invalid") from exc

    validation = JsonValidator().validate(text)
    if not validation.is_valid:
        raise ValueError("world_bank_json_invalid")

    payload = validation.data

    if _depth(payload) > MAX_JSON_DEPTH or not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("world_bank_json_shape")

    meta, records = payload
    if not isinstance(meta, dict) or not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("world_bank_json_shape")

    rows = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError("world_bank_json_record_shape")

        indicator = record.get("indicator")
        if not isinstance(indicator, dict) or indicator.get("id") != "SP.POP.TOTL":
            raise ValueError("world_bank_json_indicator_mismatch")

        if record.get("countryiso3code") != "UKR":
            raise ValueError("world_bank_json_indicator_mismatch")

        year = record.get("date")
        value = record.get("value")

        if not isinstance(year, str) or not re.fullmatch(r"(?:19|20)\d{2}", year):
            raise ValueError("world_bank_json_year_invalid")

        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or abs(float(value)) > 1e15
        ):
            raise ValueError("world_bank_json_value_invalid")

        rows.append({
            "sheet": "World Bank API",
            "sheet_index": 0,
            "table_range": "records",
            "header_cells": ["date", "value", "unit", "country"],
            "header_values": ["Year", "Population, total", "Unit", "Geography"],
            "header_checksum": "world-bank-SP.POP.TOTL-v1",
            "row": index,
            "cells": [
                {
                    "column": 1,
                    "cell": f"records[{index}].date",
                    "header": "Year",
                    "value": year,
                    "numeric_value": year,
                    "formula": False,
                },
                {
                    "column": 2,
                    "cell": f"records[{index}].value",
                    "header": "Population, total",
                    "value": str(value),
                    "numeric_value": str(value),
                    "formula": False,
                },
                {
                    "column": 3,
                    "cell": f"records[{index}].unit",
                    "header": "Unit",
                    "value": "persons",
                    "numeric_value": None,
                    "formula": False,
                },
                {
                    "column": 4,
                    "cell": f"records[{index}].countryiso3code",
                    "header": "Geography",
                    "value": "Ukraine",
                    "numeric_value": None,
                    "formula": False,
                },
            ],
            "excerpt": (
                f"World Bank API record={index} | Year={year} | "
                f"Population, total={value} | Unit=persons | Geography=Ukraine"
            ),
            "ambiguous_headers": False,
            "world_bank_provenance": {
                "url": url,
                "record_index": index,
                "indicator_id": "SP.POP.TOTL",
                "country_iso3": "UKR",
            },
        })

    return {
        "rows": rows,
        "records": len(rows),
        "indicator_id": "SP.POP.TOTL",
        "country_iso3": "UKR",
    }
