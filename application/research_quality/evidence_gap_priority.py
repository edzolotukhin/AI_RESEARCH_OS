"""Deterministic priority for bounded research gaps from persisted Evidence."""

from collections.abc import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.derivation import InformationNeedKind
from domain.planning.research_design import ResearchDesign


NO_EVIDENCE = 0
NO_QUALIFYING_EVIDENCE = 1
BELOW_SUFFICIENCY = 2


_KIND_PRIORITY = {
    InformationNeedKind.ACQUIRED: 0,
    InformationNeedKind.DERIVED: 1,
    InformationNeedKind.OUTPUT: 2,
}


def design_priority_by_need(
    design: ResearchDesign,
) -> dict[str, tuple[int, int, int, str]]:
    """Authoritative, deterministic IN ordering from the frozen Design."""
    prerequisite_ids = {
        dependency_id
        for need in design.information_needs
        for dependency_id in need.depends_on_information_need_ids
    }
    return {
        need.id: (
            _KIND_PRIORITY.get(need.kind, 3),
            0 if need.id in prerequisite_ids else 1,
            int(need.priority),
            need.id,
        )
        for need in design.information_needs
    }


def evidence_priority_by_need(
    *,
    design: ResearchDesign,
    raw: Sequence[Evidence],
    qualifying: Sequence[Evidence],
) -> dict[str, int]:
    """Rank actual claim coverage, never candidate or source coverage.

    The sufficiency evaluator decides which needs are actionable. A need with
    qualifying Evidence can still be below depth, diversity, or aspect gates.
    Sufficient needs are excluded by gap selection before these ranks apply.
    """
    raw_ids = {need_id for item in raw for need_id in item.information_need_refs}
    qualified_ids = {
        need_id for item in qualifying for need_id in item.information_need_refs
    }
    return {
        need.id: (
            NO_EVIDENCE if need.id not in raw_ids else
            NO_QUALIFYING_EVIDENCE if need.id not in qualified_ids else
            BELOW_SUFFICIENCY
        )
        for need in design.information_needs
    }
