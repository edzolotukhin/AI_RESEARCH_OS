from __future__ import annotations

from typing import Any

from domain.common.exceptions import ValidationError


def canonical_aspect_ids(value: Any, *, field_name: str = "required_aspects") -> tuple[str, ...]:
    """
    Normalize canonical aspect identifiers for deterministic comparison.

    Blank or whitespace-only identifiers are rejected. Duplicates are
    deterministically deduplicated while preserving first-seen order.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError(f"{field_name} must not contain blank identifiers")
        return (text,)
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f"{field_name} must be a sequence of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValidationError(f"{field_name} must not contain blank identifiers")
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)
