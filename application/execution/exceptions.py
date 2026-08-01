from __future__ import annotations


class ClaimConflictError(Exception):
    """Raised when a run cannot be claimed by the requesting worker."""


class LeaseLostError(Exception):
    """Raised when the worker no longer owns the run lease."""
