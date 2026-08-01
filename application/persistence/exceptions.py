class PersistenceError(Exception):
    """Base class for persistence boundary errors."""


class EntityNotFoundError(PersistenceError):
    """Raised when a requested aggregate or record does not exist."""


class DuplicateEntityError(PersistenceError):
    """Raised when creating an entity with an identifier that already exists."""


class ConcurrentModificationError(PersistenceError):
    """Raised when an optimistic concurrency check fails on save."""


class CheckpointPersistenceError(PersistenceError):
    """Raised when a durable runtime checkpoint cannot be persisted."""


class IdempotencyConflictError(PersistenceError):
    """Raised when the same idempotency key is reused with a different request."""
