"""Conservative reservation accounting; attempted/uncertain work is never refunded."""
from __future__ import annotations

from application.research_kernel.contracts import Action, KernelState


class CapacityError(RuntimeError):
    pass


class Ledger:
    def __init__(self, state: KernelState):
        self.state = state
        if not state.limits.get("decisions", 0):
            raise ValueError("finite decision limit required")
        for amounts in (state.limits, state.used, *state.reservations.values()):
            if any(type(v) is not int or v < 0 for v in amounts.values()):
                raise ValueError("invalid ledger amount")
            if any(k not in state.limits for k in amounts):
                raise ValueError("unknown ledger dimension")
        if any(self.remaining(key) < 0 for key in state.limits):
            raise ValueError("overdrawn ledger")

    def remaining(self, dimension: str) -> int:
        return (self.state.limits.get(dimension, 0)
                - self.state.used.get(dimension, 0)
                - sum(r.get(dimension, 0) for r in self.state.reservations.values()))

    def cost(self, action: Action) -> dict[str, int]:
        return {**dict(action.resources), "decisions": 1}

    def fits(self, action: Action) -> bool:
        return all(k in self.state.limits and v <= self.remaining(k)
                   for k, v in self.cost(action).items())

    def reserve(self, action: Action) -> None:
        if action.id in self.state.completed or action.id in self.state.reservations:
            raise ValueError("action identity reused")
        if not self.fits(action):
            raise CapacityError("action exceeds remaining capacity")
        self.state.reservations[action.id] = self.cost(action)

    def consume(self, action_id: str) -> None:
        # A duplicate completion is a no-op, never a second debit.
        if action_id in self.state.completed:
            return
        amounts = self.state.reservations.pop(action_id)
        for key, value in amounts.items():
            self.state.used[key] = self.state.used.get(key, 0) + value
