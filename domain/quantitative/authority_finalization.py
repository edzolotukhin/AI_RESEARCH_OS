from __future__ import annotations

from dataclasses import dataclass


AUTHORITY_FINALIZATION_METHOD_VERSION = "rl-1"


@dataclass(frozen=True)
class QuantitativeFinalizedStudyProjection:
    project_id: str
    run_id: str
    workflow_terminal_status: str
    terminal_result_id: str
    terminal_result_fingerprint: str
    terminal_outcome: str
    research_design_id: str
    research_design_fingerprint: str
    source_brief_id: str
    source_brief_fingerprint: str
    manifest_id: str
    manifest_fingerprint: str
    selection_id: str
    selection_fingerprint: str
    research_question_authorities: tuple[tuple[str, str, str], ...]
    approved_objective_authorities: tuple[tuple[str, str], ...]
    controlled_absences: tuple[tuple[str, str, str], ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    method_version: str
    fingerprint: str
