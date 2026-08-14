from __future__ import annotations

from uuid import UUID, NAMESPACE_URL, uuid5


def normalize_submission_key(value: str) -> str:
    """Return one canonical opaque form-action key or fail closed."""
    try:
        parsed = UUID((value or "").strip())
    except (ValueError, AttributeError) as exc:
        raise ValueError("submission_key must be a valid UUID") from exc
    if parsed.version != 4:
        raise ValueError("submission_key must be a UUID4 value")
    return str(parsed)


def project_id_for_submission(*, principal_id: str, submission_key: str) -> str:
    """Derive a stable owner-scoped Project identity for one logical action."""
    key = normalize_submission_key(submission_key)
    principal = (principal_id or "").strip()
    if not principal:
        raise ValueError("principal_id is required")
    return str(uuid5(NAMESPACE_URL, f"ai-research-os:{principal}:{key}"))
