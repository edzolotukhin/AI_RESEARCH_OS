"""Fail-closed validation at durable boundaries, not during ledger transitions."""
from application.research_kernel.contracts import KernelState, OutcomeKind, Stop
from application.research_kernel.ledger import Ledger


def validate_transition(previous: KernelState, current: KernelState) -> None:
    """A ledger writer cannot resurrect consumed or uncertain capacity."""
    validate_checkpoint(previous)
    validate_checkpoint(current)
    if previous.terminal is not None:
        raise ValueError("terminal kernel checkpoint is immutable")
    if any(current.completed.get(key) != value for key, value in previous.completed.items()):
        raise ValueError("completed action history is immutable")
    if current.attempted_strategies[:len(previous.attempted_strategies)] != previous.attempted_strategies:
        raise ValueError("attempted strategy history is immutable")
    old_ledger, new_ledger = Ledger(previous), Ledger(current)
    for dimension in previous.limits:
        if (current.used.get(dimension, 0) < previous.used.get(dimension, 0)
                or new_ledger.remaining(dimension) > old_ledger.remaining(dimension)):
            raise ValueError("spent or uncertain capacity cannot be restored")
    if previous.pending is not None:
        if previous.pending.id not in current.completed:
            if current.pending is None:
                raise ValueError("pending action cannot be discarded")
            from dataclasses import replace
            if replace(current.pending, resources=previous.pending.resources) != previous.pending:
                raise ValueError("pending action identity cannot change")
            old_cost, new_cost = dict(previous.pending.resources), dict(current.pending.resources)
            if old_cost.keys() != new_cost.keys() or any(new_cost[k] < v for k, v in old_cost.items()):
                raise ValueError("pending reservation cannot shrink")


def validate_checkpoint(state: KernelState, *, initial: bool = False) -> None:
    if (type(state.version) is not int or state.version != 1
            or type(state.revision) is not int or state.revision < 0):
        raise ValueError("invalid kernel checkpoint version/revision")
    if not all(isinstance(v, str) and v for v in
               (state.run_id, state.method, state.input_fingerprint)):
        raise ValueError("missing immutable kernel identity")
    ledger = Ledger(state)
    if state.terminal is not None and not isinstance(state.terminal, Stop):
        raise ValueError("unknown kernel terminal state")
    if len(state.decisions) > state.limits["decisions"]:
        raise ValueError("unbounded decision history")
    if len(set(state.attempted_strategies)) != len(state.attempted_strategies):
        raise ValueError("duplicate attempted strategy")
    expected = {} if state.pending is None else {
        state.pending.id: ledger.cost(state.pending),
    }
    if state.reservations != expected:
        raise ValueError("reservation does not match the single pending action")
    if state.pending is not None:
        if (state.pending.id in state.completed
                or state.pending.strategy_key not in state.attempted_strategies):
            raise ValueError("inconsistent pending action identity")
        if state.terminal not in (None, Stop.RECONCILIATION, Stop.SAFETY, Stop.TECHNICAL):
            raise ValueError("successful/research stop has uncertain pending work")
    for outcome in state.completed.values():
        if (not isinstance(outcome.kind, OutcomeKind)
                or any(type(v) is not int or v < 0 for v in
                       (outcome.target_gain, outcome.cross_gain))):
            raise ValueError("invalid completed outcome")
    if state.used.get("decisions", 0) != len(state.completed):
        raise ValueError("completed actions and consumed decisions disagree")
    if len(state.attempted_strategies) != len(state.completed) + bool(state.pending):
        raise ValueError("attempted strategies and action history disagree")
    if len(state.decisions) != len(state.attempted_strategies):
        raise ValueError("decision trail and action history disagree")
    if initial and (state.revision or state.used or state.reservations
                    or state.completed or state.attempted_strategies
                    or state.pending or state.terminal or state.decisions):
        raise ValueError("new kernel must start with a pristine checkpoint")
