"""Explicit JSON-compatible schema; unknown versions fail closed."""
from dataclasses import asdict

from application.research_kernel.contracts import (
    Action, KernelState, Outcome, OutcomeKind, Stop,
)
from application.research_kernel.ledger import Ledger
from application.research_kernel.checkpoint import validate_checkpoint


def encode(state: KernelState) -> dict:
    validate_checkpoint(state)
    payload = asdict(state)
    payload["terminal"] = state.terminal.value if state.terminal else None
    for outcome in payload["completed"].values():
        outcome["kind"] = outcome["kind"].value
    return payload


def decode(payload: dict) -> KernelState:
    if payload.get("version") != 1:
        raise ValueError("unsupported kernel state version")
    values = dict(payload)
    pending = values.get("pending")
    if pending is not None:
        pending = dict(pending)
        for key in ("resources", "rank", "refs"):
            pending[key] = tuple(tuple(v) if isinstance(v, (list, tuple)) else v
                                 for v in pending[key])
        values["pending"] = Action(**pending)
    values["completed"] = {
        key: Outcome(kind=OutcomeKind(item["kind"]), refs=tuple(item["refs"]),
                     target_gain=item["target_gain"], cross_gain=item["cross_gain"],
                     reason=item["reason"])
        for key, item in values["completed"].items()
    }
    values["terminal"] = Stop(values["terminal"]) if values["terminal"] else None
    state = KernelState(**values)
    validate_checkpoint(state)
    return state
