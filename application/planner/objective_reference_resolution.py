from __future__ import annotations

from collections.abc import Iterable

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief


def resolve_objective_reference_texts(
    brief: ResearchBrief | None,
    design: ResearchDesign,
    references: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Resolve objective refs without weakening the declared reference contract."""
    refs = tuple(references if references is not None else ())
    if design.objective_reference_contract == "legacy_text_v1":
        return refs
    if design.objective_reference_contract != "objective_ids_v1":
        raise ValidationError(
            f"Unsupported objective reference contract: {design.objective_reference_contract}"
        )
    if brief is None:
        raise ValidationError("objective_ids_v1 requires the current Brief")
    if brief.objective_registry is None:
        raise ValidationError("objective_ids_v1 requires an Objective Registry")
    if design.objective_registry_identity != brief.objective_registry_identity:
        raise ValidationError("Objective Registry identity does not match the Brief")
    by_id = {item.objective_id: item.text for item in brief.objective_registry}
    unknown = tuple(ref for ref in refs if ref not in by_id)
    if unknown:
        raise ValidationError(
            "Unknown objective IDs: " + ", ".join(unknown)
        )
    return tuple(by_id[ref] for ref in refs)
