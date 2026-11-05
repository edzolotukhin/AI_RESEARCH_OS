from __future__ import annotations

from typing import Iterable

DIRECT = "direct"
SEMANTIC_EXPANSION = "semantic_expansion"
SOURCE_DIVERSIFICATION = "source_diversification"
PROXY_INDICATORS = "proxy_indicators"

ALL_STRATEGIES = (DIRECT, SEMANTIC_EXPANSION, SOURCE_DIVERSIFICATION, PROXY_INDICATORS)


def choose_strategy(
    *, missing_dimensions: Iterable[str], attempted: Iterable[str], directives: Iterable[str]
) -> tuple[str, tuple[str, ...]]:
    """Choose one permitted next strategy; unknown history is never fabricated."""
    attempted_set = {str(value) for value in attempted if str(value) in ALL_STRATEGIES}
    missing = " ".join(str(value).lower() for value in (*missing_dimensions, *directives))
    if DIRECT not in attempted_set:
        selected = DIRECT
    elif any(token in missing for token in ("source", "independent", "divers", "eligib")) and SOURCE_DIVERSIFICATION not in attempted_set:
        selected = SOURCE_DIVERSIFICATION
    elif any(token in missing for token in ("proxy", "adjacent", "indicator")) and PROXY_INDICATORS not in attempted_set:
        selected = PROXY_INDICATORS
    elif SEMANTIC_EXPANSION not in attempted_set:
        selected = SEMANTIC_EXPANSION
    elif SOURCE_DIVERSIFICATION not in attempted_set:
        selected = SOURCE_DIVERSIFICATION
    elif PROXY_INDICATORS not in attempted_set and any(token in missing for token in ("metric", "observation", "period")):
        selected = PROXY_INDICATORS
    else:
        selected = ""
    remaining = tuple(strategy for strategy in ALL_STRATEGIES if strategy not in attempted_set and strategy != selected)
    return selected, remaining
