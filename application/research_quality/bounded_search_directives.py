from __future__ import annotations

from collections.abc import Sequence

from domain.research_quality.targeted_research_request import (
    MAX_TARGETED_SEARCH_DIRECTIVES,
)


def bound_targeted_search_directives(
    directives: Sequence[str],
    *,
    max_directives: int = MAX_TARGETED_SEARCH_DIRECTIVES,
) -> tuple[str, ...]:
    """Pack semantic search targets into a valid TargetedResearchRequest bound.

    Existing counts within the bound pass through unchanged. Overflow is
    coalesced into contiguous groups so every selected target remains
    represented. Order is preserved; packing is deterministic.
    """
    if max_directives < 1:
        raise ValueError("max_directives must be at least 1")

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in directives:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)

    if len(cleaned) <= max_directives:
        return tuple(cleaned)

    count = len(cleaned)
    base_size, extra = divmod(count, max_directives)
    packed: list[str] = []
    index = 0
    for slot in range(max_directives):
        size = base_size + (1 if slot < extra else 0)
        chunk = cleaned[index : index + size]
        index += size
        packed.append(" ".join(chunk))
    return tuple(packed)
