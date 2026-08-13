from __future__ import annotations

from dataclasses import replace
from typing import Callable

from domain.sources.retrieval_arm import RetrievalArm
from domain.sources.search_query import SearchQuery


MAX_INITIAL_RETRIEVAL_ARMS_PER_INFORMATION_NEED = 2


def derive_initial_retrieval_portfolio(
    query: SearchQuery,
    *,
    supports_arm: Callable[[RetrievalArm, SearchQuery], bool],
) -> tuple[SearchQuery, ...]:
    """Derive baseline plus at most one empirically justified complement."""
    baseline = replace(query, retrieval_arm=RetrievalArm.BASELINE)
    arms = [baseline]
    localized = replace(query, retrieval_arm=RetrievalArm.LOCALIZED)
    if supports_arm(RetrievalArm.LOCALIZED, localized):
        arms.append(localized)
    return tuple(arms[:MAX_INITIAL_RETRIEVAL_ARMS_PER_INFORMATION_NEED])
