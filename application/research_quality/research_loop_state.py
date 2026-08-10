from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.research_quality.research_readiness_result import ResearchReadinessResult


SHARED_LOOP_STATE_KEY = "research_loop_state"


@dataclass(frozen=True)
class ResearchLoopIterationRecord:
    attempt: int
    round_number: int
    blocking_need_ids_before: tuple[str, ...]
    targeted_need_ids: tuple[str, ...]
    queries_generated: int
    new_sources_count: int
    new_evidence_count: int
    readiness_after: dict[str, Any]
    improved: bool
    extraction_attempted: bool = True
    budget_stop_reason: str | None = None
    reused_need_ids: tuple[str, ...] = ()
    reassessed_need_ids: tuple[str, ...] = ()
    missing_need_ids: tuple[str, ...] = ()
    remediation_attempt_diagnostics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "attempt": self.attempt,
            "round_number": self.round_number,
            "blocking_need_ids_before": list(self.blocking_need_ids_before),
            "targeted_need_ids": list(self.targeted_need_ids),
            "queries_generated": self.queries_generated,
            "new_sources_count": self.new_sources_count,
            "new_evidence_count": self.new_evidence_count,
            "readiness_after": self.readiness_after,
            "improved": self.improved,
            "extraction_attempted": self.extraction_attempted,
            "budget_stop_reason": self.budget_stop_reason,
            "reused_need_ids": list(self.reused_need_ids),
            "reassessed_need_ids": list(self.reassessed_need_ids),
            "missing_need_ids": list(self.missing_need_ids),
        }
        if self.remediation_attempt_diagnostics is not None:
            payload["remediation_attempt_diagnostics"] = dict(
                self.remediation_attempt_diagnostics,
            )
        return payload


@dataclass
class ResearchLoopState:
    research_loop_count: int = 0
    current_round: int = 0
    gap_attempt_counts: dict[str, int] = field(default_factory=dict)
    pending_targeted_need_id: str = ""
    pending_attempt: int = 0
    termination_reason: str = ""
    history: list[ResearchLoopIterationRecord] | None = None
    previous_readiness_result: dict[str, Any] | None = None
    scheduler_decisions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []
        if self.scheduler_decisions is None:
            self.scheduler_decisions = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_loop_count": self.research_loop_count,
            "current_round": self.current_round,
            "gap_attempt_counts": dict(self.gap_attempt_counts),
            "pending_targeted_need_id": self.pending_targeted_need_id,
            "pending_attempt": self.pending_attempt,
            "termination_reason": self.termination_reason,
            "history": [item.to_dict() for item in (self.history or [])],
            "previous_readiness_result": self.previous_readiness_result,
            "scheduler_decisions": [dict(item) for item in self.scheduler_decisions],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchLoopState:
        history = [
            ResearchLoopIterationRecord(
                attempt=int(item["attempt"]),
                round_number=int(item.get("round_number", 0)),
                blocking_need_ids_before=tuple(
                    str(value) for value in item.get("blocking_need_ids_before", [])
                ),
                targeted_need_ids=tuple(
                    str(value) for value in item.get("targeted_need_ids", [])
                ),
                queries_generated=int(item.get("queries_generated", 0)),
                new_sources_count=int(item.get("new_sources_count", 0)),
                new_evidence_count=int(item.get("new_evidence_count", 0)),
                readiness_after=dict(item.get("readiness_after", {})),
                improved=bool(item.get("improved", False)),
                extraction_attempted=bool(item.get("extraction_attempted", True)),
                budget_stop_reason=item.get("budget_stop_reason"),
                reused_need_ids=tuple(
                    str(value) for value in item.get("reused_need_ids", [])
                ),
                reassessed_need_ids=tuple(
                    str(value) for value in item.get("reassessed_need_ids", [])
                ),
                missing_need_ids=tuple(
                    str(value) for value in item.get("missing_need_ids", [])
                ),
                remediation_attempt_diagnostics=(
                    dict(item["remediation_attempt_diagnostics"])
                    if isinstance(item.get("remediation_attempt_diagnostics"), dict)
                    else None
                ),
            )
            for item in payload.get("history", [])
        ]
        raw_counts = payload.get("gap_attempt_counts") or {}
        gap_attempt_counts = {
            str(need_id): int(count)
            for need_id, count in raw_counts.items()
        }
        scheduler_decisions = [
            dict(item)
            for item in payload.get("scheduler_decisions") or []
            if isinstance(item, dict)
        ]
        return cls(
            research_loop_count=int(payload.get("research_loop_count", 0)),
            current_round=int(payload.get("current_round", 0)),
            gap_attempt_counts=gap_attempt_counts,
            pending_targeted_need_id=str(payload.get("pending_targeted_need_id", "")),
            pending_attempt=int(payload.get("pending_attempt", 0)),
            termination_reason=str(payload.get("termination_reason", "")),
            history=history,
            previous_readiness_result=payload.get("previous_readiness_result"),
            scheduler_decisions=scheduler_decisions,
        )


def serialize_readiness(result: ResearchReadinessResult, *, research_outcome: str) -> dict[str, Any]:
    payload = result.to_dict()
    payload["research_outcome"] = research_outcome
    return payload
