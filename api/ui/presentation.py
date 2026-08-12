"""Template helpers and presentation constants for Research UI."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

from markupsafe import Markup, escape

from application.query.research_status import ResearchPhase

PHASE_ORDER: tuple[ResearchPhase, ...] = (
    ResearchPhase.QUEUED,
    ResearchPhase.PLANNING,
    ResearchPhase.RESEARCHING,
    ResearchPhase.EVALUATING,
    ResearchPhase.ANALYZING,
    ResearchPhase.WRITING,
    ResearchPhase.REVIEWING,
    ResearchPhase.COMPLETED,
)

PHASE_LABELS: dict[str, str] = {
    ResearchPhase.QUEUED.value: "Research request queued",
    ResearchPhase.PLANNING.value: "Planning the research",
    ResearchPhase.RESEARCHING.value: "Finding and evaluating sources",
    ResearchPhase.EVALUATING.value: "Checking whether the evidence is sufficient",
    ResearchPhase.ANALYZING.value: "Analyzing supported evidence",
    ResearchPhase.WRITING.value: "Preparing the report",
    ResearchPhase.REVIEWING.value: "Reviewing research quality",
    ResearchPhase.COMPLETED.value: "Research process completed",
}

OUTCOME_LABELS: dict[str, str] = {
    "APPROVED": "Approved",
    "NOT_READY": "Not ready for analysis",
    "QUALITY_REJECTED": "Quality not approved",
    "EXECUTION_FAILED": "Execution failed",
}

OUTCOME_CSS: dict[str, str] = {
    "APPROVED": "outcome-approved",
    "NOT_READY": "outcome-not-ready",
    "QUALITY_REJECTED": "outcome-quality-rejected",
    "EXECUTION_FAILED": "outcome-execution-failed",
}

NOT_READY_MESSAGE = (
    "Research completed, but the available evidence was not sufficient to safely "
    "produce a final analysis or report."
)
QUALITY_REJECTED_MESSAGE = (
    "Research reached report and review, but the quality gate did not approve "
    "the final artifact."
)
EXECUTION_FAILED_MESSAGE = (
    "Research could not complete because of a technical execution problem."
)

_LIST_SPLIT_RE = re.compile(r"[\n,;]+")


def split_list_field(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in _LIST_SPLIT_RE.split(value) if item.strip()]


def phase_index(phase: str) -> int:
    try:
        return PHASE_ORDER.index(ResearchPhase(phase))
    except ValueError:
        return 0


def safe_text(value: Any) -> str:
    return escape(str(value or ""))


def bounded_text(value: dict[str, Any] | str | None) -> Markup:
    if isinstance(value, dict):
        text = str(value.get("value", ""))
        truncated = bool(value.get("truncated"))
        original = value.get("original_length")
    else:
        text = str(value or "")
        truncated = False
        original = len(text)
    escaped = escape(text).replace("\n", Markup("<br>"))
    if truncated:
        return Markup(
            f'{escaped}<p class="truncation-note">Truncated '
            f"({original} characters total).</p>",
        )
    return Markup(escaped)


def safe_external_url(url: str | None) -> dict[str, Any]:
    raw = str(url or "").strip()
    if not raw:
        return {"href": None, "display": ""}
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return {"href": raw, "display": raw}
    return {"href": None, "display": raw}


def brief_form_defaults() -> dict[str, Any]:
    return {
        "title": "",
        "business_question": "",
        "objectives": "",
        "geography": "",
        "timeframe": "",
        "market": "",
        "target_entities": "",
        "constraints": "",
        "deliverables": "",
        "language": "en",
        "context": "",
        "known_information": "",
        "exclusions": "",
    }


def build_result_view_model(detail_payload: dict[str, Any]) -> dict[str, Any]:
    inner = detail_payload.get("detail") or {}
    evidence_by_id = {item["id"]: item for item in inner.get("evidence", [])}
    sources_by_id = {item["id"]: item for item in inner.get("sources", [])}
    findings = []
    for finding in inner.get("findings", []):
        linked_evidence = [
            evidence_by_id[eid]
            for eid in finding.get("evidence_refs", [])
            if eid in evidence_by_id
        ]
        findings.append({**finding, "linked_evidence": linked_evidence})
    return {
        **detail_payload,
        "inner": inner,
        "evidence_by_id": evidence_by_id,
        "sources_by_id": sources_by_id,
        "findings_enriched": findings,
    }


def parse_brief_form(form: dict[str, str]) -> dict[str, Any]:
    return {
        "title": form.get("title", "").strip(),
        "business_question": form.get("business_question", "").strip(),
        "objectives": split_list_field(form.get("objectives")),
        "geography": split_list_field(form.get("geography")),
        "market": form.get("market", "").strip(),
        "target_entities": split_list_field(form.get("target_entities")),
        "timeframe": form.get("timeframe", "").strip(),
        "constraints": split_list_field(form.get("constraints")),
        "deliverables": split_list_field(form.get("deliverables")),
        "language": (form.get("language") or "en").strip() or "en",
        "context": form.get("context", "").strip(),
        "known_information": split_list_field(form.get("known_information")),
        "exclusions": split_list_field(form.get("exclusions")),
    }
