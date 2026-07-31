from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from application.persistence.exceptions import (
    ConcurrentModificationError,
    EntityNotFoundError,
)


def atomic_update_version(
    session: Session,
    model: type,
    entity_id: str,
    *,
    expected_version: int | None,
    values: dict,
) -> int:
    """
    Apply an optimistic-concurrency update in a single SQL statement.

    Returns the new version after a successful update.
    """
    current = session.get(model, entity_id)
    if current is None:
        raise EntityNotFoundError(f"{model.__name__} not found: {entity_id}")

    stored_version = int(getattr(current, "version"))
    if expected_version is not None and expected_version != stored_version:
        raise ConcurrentModificationError(
            f"{model.__name__} {entity_id} version mismatch: "
            f"expected {expected_version}, found {stored_version}."
        )

    new_version = stored_version + 1
    update_values = dict(values)
    update_values["version"] = new_version

    result = session.execute(
        update(model)
        .where(
            model.id == entity_id,
            model.version == stored_version,
        )
        .values(**update_values)
    )

    if result.rowcount != 1:
        raise ConcurrentModificationError(
            f"{model.__name__} {entity_id} concurrent modification detected."
        )

    return new_version


def atomic_delete_version(
    session: Session,
    model: type,
    entity_id: str,
    *,
    expected_version: int | None,
) -> None:
    """Delete an entity with optional optimistic concurrency."""
    current = session.get(model, entity_id)
    if current is None:
        raise EntityNotFoundError(f"{model.__name__} not found: {entity_id}")

    stored_version = int(getattr(current, "version"))
    if expected_version is not None and expected_version != stored_version:
        raise ConcurrentModificationError(
            f"{model.__name__} {entity_id} version mismatch: "
            f"expected {expected_version}, found {stored_version}."
        )

    if expected_version is None:
        session.delete(current)
        return

    result = session.execute(
        delete(model).where(
            model.id == entity_id,
            model.version == stored_version,
        )
    )

    if result.rowcount != 1:
        raise ConcurrentModificationError(
            f"{model.__name__} {entity_id} concurrent modification detected."
        )
