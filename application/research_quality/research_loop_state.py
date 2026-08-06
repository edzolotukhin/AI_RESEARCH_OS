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

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "round_number": self.round_number,
            "blocking_need_ids_before": list(self.blocking_need_ids_before),
            "targeted_need_ids": list(self.targeted_need_ids),
            "queries_generated": self.queries_generated,
            "new_sources_count": self.new_sources_count,
            "new_evidence_count": self.new_evidence_count,
            "readiness_after": self.readiness_after,
            "improved": self.improved,
        }


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

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

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
            )
            for item in payload.get("history", [])
        ]
        raw_counts = payload.get("gap_attempt_counts") or {}
        gap_attempt_counts = {
            str(need_id): int(count)
            for need_id, count in raw_counts.items()
        }
        return cls(
            research_loop_count=int(payload.get("research_loop_count", 0)),
            current_round=int(payload.get("current_round", 0)),
            gap_attempt_counts=gap_attempt_counts,
            pending_targeted_need_id=str(payload.get("pending_targeted_need_id", "")),
            pending_attempt=int(payload.get("pending_attempt", 0)),
            termination_reason=str(payload.get("termination_reason", "")),
            history=history,
            previous_readiness_result=payload.get("previous_readiness_result"),
        )


def serialize_readiness(result: ResearchReadinessResult, *, research_outcome: str) -> dict[str, Any]:
    payload = result.to_dict()
    payload["research_outcome"] = research_outcome
    return payload
