from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionLogEntry:
    """
    Append-only execution audit record.

    Lives at the persistence boundary; not a domain aggregate.
    """

    event_id: str
    run_id: str
    event_type: str
    timestamp: str
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeItem:
    """Project-scoped knowledge reference persisted outside the domain core."""

    id: str
    project_id: str
    title: str
    content: str
    version: int = 1


@dataclass
class ArtifactRecord:
    """Persisted artifact metadata with storage identity."""

    id: str
    project_id: str
    artifact_type: str
    title: str
    content: str
    run_id: str | None = None
    status: str = "Draft"
    version: int = 1
