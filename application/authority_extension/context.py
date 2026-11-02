from __future__ import annotations

from application.authority_extension.reader import AuthorityCompositionError

COMPOSED_AUTHORITY_KEY = "research_authority_composition_v1"


def composition_for_context(context, repository):
    payload = context.read_shared(COMPOSED_AUTHORITY_KEY)
    if payload is None:
        return None
    if repository is None or not isinstance(payload, dict):
        raise AuthorityCompositionError("composed authority repository or payload is missing")
    composition_id = payload.get("composition_id")
    digest = payload.get("composition_digest")
    if not isinstance(composition_id, str) or not isinstance(digest, str):
        raise AuthorityCompositionError("composed authority identity is malformed")
    composition = repository.get_by_id(composition_id)
    if composition is None or composition.composition_digest != digest:
        raise AuthorityCompositionError("composed authority identity/digest mismatch")
    if composition.project_id != context.project.id:
        raise AuthorityCompositionError("composed authority belongs to another project")
    design = context.workflow_template.research_design_snapshot
    if design is None or composition.research_design_id != design.id:
        raise AuthorityCompositionError("composed authority belongs to another design")
    return composition
