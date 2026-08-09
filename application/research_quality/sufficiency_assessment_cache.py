"""Run-scoped incremental sufficiency assessment cache (P1-07.11)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from domain.research_quality.information_need_assessment import InformationNeedAssessment

from application.research_quality.sufficiency_assessment_fingerprint import (
    SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION,
)
from runtime.workflow_context import WorkflowContext

SHARED_SUFFICIENCY_CACHE_KEY = "sufficiency_assessment_cache"

_current_cache: ContextVar["SufficiencyAssessmentCache | None"] = ContextVar(
    "sufficiency_assessment_cache",
    default=None,
)


@dataclass
class SufficiencyAssessmentCache:
    contract_version: str = SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    semantic_assessment_calls: int = 0
    reused_assessments: int = 0
    reassessed_fingerprint_changed: int = 0
    missing_no_evidence: int = 0
    missing_prior_state: int = 0
    reused_need_ids: list[str] = field(default_factory=list)
    reassessed_need_ids: list[str] = field(default_factory=list)
    missing_need_ids: list[str] = field(default_factory=list)

    def reset_pass_diagnostics(self) -> None:
        self.reused_need_ids = []
        self.reassessed_need_ids = []
        self.missing_need_ids = []

    def lookup(
        self,
        information_need_id: str,
        fingerprint: str,
    ) -> InformationNeedAssessment | None:
        entry = self.entries.get(information_need_id)
        if not isinstance(entry, dict):
            self.missing_prior_state += 1
            return None
        if entry.get("contract_version") != self.contract_version:
            return None
        if entry.get("fingerprint") != fingerprint:
            self.reassessed_fingerprint_changed += 1
            return None
        payload = entry.get("assessment")
        if not isinstance(payload, dict):
            return None
        try:
            assessment = InformationNeedAssessment.from_dict(payload)
        except Exception:
            return None
        self.reused_assessments += 1
        self.reused_need_ids.append(information_need_id)
        return assessment

    def store(
        self,
        *,
        information_need_id: str,
        fingerprint: str,
        assessment: InformationNeedAssessment,
    ) -> None:
        self.entries[information_need_id] = {
            "contract_version": self.contract_version,
            "fingerprint": fingerprint,
            "assessment": assessment.to_dict(),
        }
        self.semantic_assessment_calls += 1
        self.reassessed_need_ids.append(information_need_id)

    def record_missing(self, information_need_id: str) -> None:
        self.missing_no_evidence += 1
        self.missing_need_ids.append(information_need_id)

    def diagnostics_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "semantic_assessment_calls": self.semantic_assessment_calls,
            "reused_assessments": self.reused_assessments,
            "reassessed_fingerprint_changed": self.reassessed_fingerprint_changed,
            "missing_no_evidence": self.missing_no_evidence,
            "missing_prior_state": self.missing_prior_state,
            "reused_need_ids": list(self.reused_need_ids),
            "reassessed_need_ids": list(self.reassessed_need_ids),
            "missing_need_ids": list(self.missing_need_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "entries": dict(self.entries),
            "semantic_assessment_calls": self.semantic_assessment_calls,
            "reused_assessments": self.reused_assessments,
            "reassessed_fingerprint_changed": self.reassessed_fingerprint_changed,
            "missing_no_evidence": self.missing_no_evidence,
            "missing_prior_state": self.missing_prior_state,
            "reused_need_ids": list(self.reused_need_ids),
            "reassessed_need_ids": list(self.reassessed_need_ids),
            "missing_need_ids": list(self.missing_need_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> SufficiencyAssessmentCache:
        if not isinstance(payload, dict):
            return cls()
        stored_version = str(
            payload.get("contract_version") or SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION
        )
        entries_raw = payload.get("entries") or {}
        entries: dict[str, dict[str, Any]] = {}
        if isinstance(entries_raw, dict):
            for need_id, entry in entries_raw.items():
                if isinstance(entry, dict):
                    entries[str(need_id)] = dict(entry)
        return cls(
            contract_version=stored_version,
            entries=entries,
            semantic_assessment_calls=int(payload.get("semantic_assessment_calls", 0)),
            reused_assessments=int(payload.get("reused_assessments", 0)),
            reassessed_fingerprint_changed=int(
                payload.get("reassessed_fingerprint_changed", 0)
            ),
            missing_no_evidence=int(payload.get("missing_no_evidence", 0)),
            missing_prior_state=int(payload.get("missing_prior_state", 0)),
            reused_need_ids=[
                str(item) for item in payload.get("reused_need_ids", [])
            ],
            reassessed_need_ids=[
                str(item) for item in payload.get("reassessed_need_ids", [])
            ],
            missing_need_ids=[
                str(item) for item in payload.get("missing_need_ids", [])
            ],
        )


def get_sufficiency_assessment_cache() -> SufficiencyAssessmentCache | None:
    return _current_cache.get()


def bind_sufficiency_assessment_cache(
    context: WorkflowContext,
) -> SufficiencyAssessmentCache:
    payload = context.read_shared(SHARED_SUFFICIENCY_CACHE_KEY)
    cache = SufficiencyAssessmentCache.from_dict(
        payload if isinstance(payload, dict) else None
    )
    cache.reset_pass_diagnostics()
    _current_cache.set(cache)
    return cache


def persist_sufficiency_assessment_cache(context: WorkflowContext) -> None:
    cache = _current_cache.get()
    if cache is None:
        return
    context.write_shared(SHARED_SUFFICIENCY_CACHE_KEY, cache.to_dict())


def reset_sufficiency_assessment_cache(
    previous: SufficiencyAssessmentCache | None,
) -> None:
    _current_cache.set(previous)


def clear_sufficiency_assessment_cache() -> None:
    _current_cache.set(None)
