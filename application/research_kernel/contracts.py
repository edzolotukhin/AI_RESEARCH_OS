"""Kernel contracts contain no Desk, provider, or persistence implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Stop(str, Enum):
    READY = "ready"
    BUDGET = "insufficient_budget"
    OPPORTUNITIES = "insufficient_opportunities"
    RECONCILIATION = "reconciliation_required"
    TECHNICAL = "failed_technical"
    SAFETY = "stopped_safety"


class OutcomeKind(str, Enum):
    TARGET = "productive_target"
    CROSS = "productive_cross_only"
    EMPTY = "valid_empty"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    ACQUISITION_FAILED = "acquisition_failed"
    INVALID = "invalid_response"


@dataclass(frozen=True)
class Gap:
    need_id: str
    reason: str
    priority: int
    qualifying_count: int = 0
    aspects: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observation:
    fingerprint: str
    gaps: tuple[Gap, ...]
    sufficient: bool = False
    safety_stop: bool = False


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    target: str
    strategy_key: str
    reason: str
    resources: tuple[tuple[str, int], ...]
    rank: tuple[int, ...] = ()
    # Safe canonical identifiers, never provider text or mutable research payloads.
    refs: tuple[str, ...] = ()
    max_attempts: int = 0

    def __post_init__(self):
        if type(self.max_attempts) is not int or self.max_attempts < 0:
            raise ValueError("invalid per-action attempt ceiling")
        if not all((self.id, self.kind, self.strategy_key, self.reason)):
            raise ValueError("action identity and reason required")
        names = [key for key, _ in self.resources]
        if len(names) != len(set(names)) or "decisions" in names:
            raise ValueError("duplicate or controller-owned resource")
        if any(type(value) is not int or value < 0 for _, value in self.resources):
            raise ValueError("resource amounts must be nonnegative integers")


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    refs: tuple[str, ...] = ()
    target_gain: int = 0
    cross_gain: int = 0
    reason: str = ""


@dataclass
class KernelState:
    run_id: str
    method: str
    input_fingerprint: str
    limits: dict[str, int]
    version: int = 1
    revision: int = 0
    used: dict[str, int] = field(default_factory=dict)
    reservations: dict[str, dict[str, int]] = field(default_factory=dict)
    completed: dict[str, Outcome] = field(default_factory=dict)
    attempted_strategies: list[str] = field(default_factory=list)
    pending: Action | None = None
    terminal: Stop | None = None
    decisions: list[dict] = field(default_factory=list)


class StateStore(Protocol):
    """Durable adapter must fence owner/lease and compare revision atomically.

    load returns an independent snapshot. save commits or raises; never silently
    ignores an absent checkpoint. expected_revision=-1 means create-if-absent.
    """
    def load(self) -> KernelState | None: ...
    def save(self, state: KernelState, *, expected_revision: int) -> None: ...
    def authorize_dispatch(self, state: KernelState) -> None: ...


class MethodAdapter(Protocol):
    method_id: str
    def observe(self, state: KernelState) -> Observation: ...
    def propose(self, state: KernelState, observation: Observation) -> tuple[Action, ...]: ...
    def execute(self, action: Action) -> Outcome: ...
    def validate(self, action: Action, outcome: Outcome) -> Outcome: ...


class Observer(Protocol):
    def __call__(self, event: dict) -> None: ...
