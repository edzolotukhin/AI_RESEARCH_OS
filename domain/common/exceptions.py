"""
Domain exceptions.

The Domain layer never raises generic Python exceptions such as
ValueError or RuntimeError. All business and invariant violations
must derive from DomainError.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain exceptions."""


class ValidationError(DomainError):
    """Raised when business validation fails."""


class InvariantViolationError(DomainError):
    """Raised when an aggregate invariant is violated."""