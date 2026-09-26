"""Single-flight deterministic controller; persistence failure prevents dispatch."""
from __future__ import annotations

from copy import deepcopy

from application.research_kernel.contracts import (
    KernelState, MethodAdapter, Observer, Outcome, StateStore, Stop,
)
from application.research_kernel.ledger import Ledger
from application.research_kernel.checkpoint import validate_checkpoint
from application.research_kernel.dispatch import dispatch_scope
from application.execution.exceptions import BudgetExhaustedError
from application.research_kernel.contracts import OutcomeKind


class Controller:
    def __init__(self, store: StateStore, method: MethodAdapter, observer: Observer | None = None):
        self.store, self.method, self.observer = store, method, observer

    def _save(self, state: KernelState) -> None:
        validate_checkpoint(state)
        previous = state.revision
        state.revision += 1
        self.store.save(deepcopy(state), expected_revision=previous)

    def _emit(self, event: dict) -> None:
        if self.observer:
            try:
                self.observer(deepcopy(event))
            except Exception:
                # Optional observations never govern policy or replace outcomes.
                pass

    def run(self, initial: KernelState) -> KernelState:
        validate_checkpoint(initial, initial=True)
        if initial.version != 1 or initial.method != self.method.method_id:
            raise ValueError("unsupported requested kernel or method version")
        state = self.store.load()
        if state is None:
            state = deepcopy(initial)
            Ledger(state)
            self.store.save(deepcopy(state), expected_revision=-1)
        validate_checkpoint(state)
        if (state.version != 1 or state.method != self.method.method_id
                or state.run_id != initial.run_id
                or state.input_fingerprint != initial.input_fingerprint
                or state.limits != initial.limits):
            raise ValueError("kernel version, identity or envelope mismatch")
        if state.terminal:
            return state
        if state.pending is not None:
            # No proof of non-dispatch: retain the complete reservation and stop.
            state.terminal = Stop.RECONCILIATION
            self._save(state)
            return state
        ledger = Ledger(state)
        while state.terminal is None:
            observation = self.method.observe(deepcopy(state))
            if observation.safety_stop:
                state.terminal = Stop.SAFETY
                break
            if observation.sufficient:
                state.terminal = Stop.READY
                break
            if ledger.remaining("decisions") <= 0:
                state.terminal = Stop.BUDGET
                break
            proposals = self.method.propose(deepcopy(state), observation)
            if len(proposals) > state.limits["decisions"]:
                raise ValueError("unbounded proposal set")
            actions = sorted((a for a in proposals
                              if a.strategy_key not in state.attempted_strategies
                              and a.id not in state.completed), key=lambda a: (a.rank, a.id))
            eligible = [a for a in actions if ledger.fits(a)]
            if not eligible:
                state.terminal = Stop.BUDGET if actions else Stop.OPPORTUNITIES
                break
            action = eligible[0]
            ledger.reserve(action)
            state.pending = action
            state.attempted_strategies.append(action.strategy_key)
            decision = {
                "state_revision": state.revision,
                "observation": observation.fingerprint,
                "gaps": [[g.need_id, g.reason] for g in observation.gaps],
                "eligible": [a.id for a in eligible],
                "action": action.id, "reason": action.reason,
                "reservation": ledger.cost(action),
            }
            state.decisions.append(decision)
            self._save(state)  # Must complete durably before any method side effect.
            self._emit(decision)
            self.store.authorize_dispatch(deepcopy(state))
            stop_after = False
            try:
                with dispatch_scope(state, self._save) as dispatch:
                    outcome = self.method.validate(action, self.method.execute(action))
                    if dispatch.ambiguous:
                        raise RuntimeError("ambiguous provider attempt requires reconciliation")
                if not isinstance(outcome, Outcome):
                    raise TypeError("unrecognized method outcome")
            except BudgetExhaustedError:
                outcome = Outcome(OutcomeKind.INVALID, reason="bounded_provider_capacity")
                stop_after = True
            except Exception:
                # Do not persist arbitrary exception/provider payloads.
                state.terminal = Stop.RECONCILIATION
                self._save(state)
                return state
            ledger.consume(action.id)
            state.completed[action.id] = outcome
            state.pending = None
            decision["outcome"] = outcome.kind.value
            decision["target_gain"] = outcome.target_gain
            decision["cross_gain"] = outcome.cross_gain
            self._save(state)
            self._emit({"action": action.id, "outcome": outcome.kind.value})
            if stop_after:
                state.terminal = Stop.BUDGET
                break
        self._save(state)
        self._emit({"stop": state.terminal.value})
        return state
