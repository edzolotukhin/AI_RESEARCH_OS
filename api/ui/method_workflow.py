"""Presentation-only method workflow guidance derived from persisted state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class MethodWorkflowGuidance:
    stage: str
    state: str
    explanation: str
    action_label: str
    action_target: str
    completed: tuple[str, ...]


def qualitative_workflow_guidance(
    records: Iterable[object], *, project_id: str, run_id: str
) -> MethodWorkflowGuidance:
    """Derive guidance only; authorization and lifecycle remain server-owned."""
    values = tuple(records)
    kinds = tuple(str(getattr(item, "record_type", "")) for item in values)
    payloads = tuple(getattr(item, "payload", {}) for item in values)
    completed: list[str] = []
    if "participant" not in kinds:
        return MethodWorkflowGuidance("Research material", "Needs attention", "Add a participant and confirm consent before adding interview material.", "Add participant", "#participants", ())
    completed.append("Participant added")
    eligible = any(kind == "consent" and isinstance(payload, dict) and payload.get("state") == "eligible" for kind, payload in zip(kinds, payloads))
    if not eligible:
        return MethodWorkflowGuidance("Research material", "Needs attention", "Confirm that the material may be used in this research.", "Confirm consent", "#consent", tuple(completed))
    completed.append("Consent confirmed")
    if "session" not in kinds:
        return MethodWorkflowGuidance("Research material", "Ready", "Create an interview session; your existing setup is preserved.", "Create session", "#sessions", tuple(completed))
    completed.append("Session created")
    if "transcript" not in kinds:
        return MethodWorkflowGuidance("Transcript", "Ready", "Upload a prepared transcript (recommended), or use audio when privacy policy permits.", "Upload prepared transcript", "#source-choice", tuple(completed))
    completed.append("Transcript available")
    if "thematic_revision" not in kinds:
        return MethodWorkflowGuidance("Thematic analysis", "In progress", "Build the corpus, code the material, and review supported themes.", "Continue thematic analysis", "#analysis", tuple(completed))
    completed.append("Themes available")
    accepted_findings = any(kind == "qualitative_finding" and isinstance(payload, dict) and payload.get("status") == "accepted" for kind, payload in zip(kinds, payloads))
    if not accepted_findings:
        return MethodWorkflowGuidance("Conclusions", "Ready", "Themes are ready. Draft and accept evidence-backed findings before review.", "Review conclusions", "#conclusions", tuple(completed))
    completed.append("Conclusions prepared")
    if "qualitative_approved_revision" not in kinds:
        return MethodWorkflowGuidance("Review", "Needs decision", "Submit selected findings and insights for explicit human review.", "Continue to review", "#review", tuple(completed))
    completed.append("Approved Version created")
    final_report = any(kind == "qualitative_report_revision" and isinstance(payload, dict) and payload.get("status") == "final" for kind, payload in zip(kinds, payloads))
    if not final_report:
        return MethodWorkflowGuidance("Report", "Ready", "The Approved Version is fixed. Create and finalize its report.", "Create report", "#deliverables", tuple(completed))
    completed.append("Report finalized")
    return MethodWorkflowGuidance("Outputs", "Complete", "The approved report is ready for immutable PDF and PowerPoint outputs.", "Open project outputs", f"/ui/projects/{project_id}/outputs", tuple(completed))


__all__ = ["MethodWorkflowGuidance", "qualitative_workflow_guidance"]
