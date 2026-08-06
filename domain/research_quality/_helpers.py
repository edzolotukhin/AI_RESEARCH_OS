from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from domain.common.exceptions import ValidationError

_E = TypeVar("_E", bound=Enum)


def tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, (list, tuple)):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return tuple(normalized)
    return ()


def tuple_of_enum(enum_type: type[_E], value: Any) -> tuple[_E, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        value = (value,)
    normalized: list[_E] = []
    seen: set[_E] = set()
    for item in value:
        member = item if isinstance(item, enum_type) else enum_type(str(item))
        if member in seen:
            continue
        seen.add(member)
        normalized.append(member)
    return tuple(normalized)


def validate_non_negative_count(field_name: str, value: int) -> None:
    if value < 0:
        raise ValidationError(f"{field_name} must be >= 0, got {value}")


def validate_unit_score(field_name: str, value: float | None) -> None:
    if value is None:
        return
    if not 0.0 <= value <= 1.0:
        raise ValidationError(
            f"{field_name} must be between 0 and 1 inclusive, got {value}",
        )
