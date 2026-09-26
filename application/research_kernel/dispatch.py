"""Durable child-attempt accounting for the current single-flight action.

No provider payload is retained. Transport and structured retries share the same
action reservation and cannot obtain a new envelope after worker restart.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace

from application.execution.exceptions import BudgetExhaustedError
from application.research_kernel.ledger import Ledger

_active = ContextVar("research_kernel_dispatch", default=None)


def current_dispatch():
    return _active.get()


class Dispatch:
    def __init__(self, state, save):
        self.state, self.save = state, save
        self.unit = {k: v for k, v in state.pending.resources if not k.startswith("logical:")}
        self.count = 0
        self.ambiguous = False

    def mark_ambiguous(self):
        self.ambiguous = True
        self.state.decisions[-1]["attempts"][-1]["outcome"] = "ambiguous"
        self.save(self.state)

    def invoke(self, provider, operation, call, *, retry=False):
        if self.ambiguous:
            raise RuntimeError("ambiguous provider attempt requires reconciliation")
        state = self.state
        action = state.pending
        if action.max_attempts and self.count >= action.max_attempts:
            raise BudgetExhaustedError("kernel_attempt_capacity", stage=operation)
        amounts = dict(action.resources)
        if self.count:
            extra = dict(self.unit)
            if "retries" in amounts:
                extra["retries"] = int(retry)
            ledger = Ledger(state)
            if any(value > ledger.remaining(key) for key, value in extra.items()):
                raise BudgetExhaustedError("kernel_attempt_capacity", stage=operation)
            amounts.update({key: amounts[key] + value for key, value in extra.items()})
            state.pending = replace(action, resources=tuple(amounts.items()))
            state.reservations[action.id] = {**amounts, "decisions": 1}
        self.count += 1
        entry = {"action": action.id, "ordinal": self.count, "provider": provider,
                 "operation": operation, "retry": bool(retry), "outcome": "ambiguous",
                 "reservation": deepcopy(state.reservations[action.id])}
        state.decisions[-1].setdefault("attempts", []).append(entry)
        state.decisions[-1]["reservation"] = deepcopy(state.reservations[action.id])
        self.save(state)  # Lease + revision fencing and reservation precede call.
        try:
            result = call()
        except Exception:
            entry["outcome"] = "failed"
            self.save(state)
            raise
        entry["outcome"] = "returned"
        self.save(state)
        return result


@contextmanager
def dispatch_scope(state, save):
    token = _active.set(Dispatch(state, save))
    try:
        yield _active.get()
    finally:
        _active.reset(token)


def invoke(provider, operation, call, *, retry=False):
    scope = current_dispatch()
    return scope.invoke(provider, operation, call, retry=retry) if scope else call()
