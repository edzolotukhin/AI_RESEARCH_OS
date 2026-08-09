"""
Build brief-aligned ResearchDesign JSON for offline/deterministic planner mode.

Parses planner prompt sections so objective_refs, geography, and timeframe
match the submitted ResearchBrief regardless of brief field values.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.ai.prompt import Prompt

_DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "llm"
    / "fixtures"
    / "deterministic_planner_response.json"
)


def build_deterministic_design_response(prompt: Prompt) -> str:
    """Return ResearchDesign JSON aligned with brief fields in the prompt."""
    template = _load_template()
    objectives = _parse_bullet_list(
        prompt.user,
        heading="Objectives:",
        stop_before=("Geography:", "Market:", "Timeframe:"),
    )
    geography = _parse_bullet_list(
        prompt.user,
        heading="Geography:",
        stop_before=("Market:", "Target Entities:", "Timeframe:"),
    )
    timeframe = _parse_scalar(
        prompt.user,
        heading="Timeframe:",
        stop_before=("Constraints:", "Deliverables:", "Language:"),
    )
    language = _parse_scalar(
        prompt.user,
        heading="Language:",
        stop_before=("Context:", "Known Information:", "Exclusions:", "---"),
    ) or "en"

    if not objectives:
        objectives = ["Complete the stated research goal."]

    geo_label = geography[0] if geography else "Not specified"
    time_label = timeframe if timeframe and timeframe != "Not specified" else "Current period"

    questions = []
    for index, objective in enumerate(objectives, start=1):
        questions.append(
            {
                "id": f"rq-{index}",
                "question": f"What evidence is required to address: {objective}?",
                "objective_refs": [objective],
                "priority": min(index, 5),
                "rationale": "Derived from brief objective.",
            }
        )

    needs = []
    for question in questions:
        needs.append(
            {
                "id": f"in-{question['id']}",
                "research_question_id": question["id"],
                "description": (
                    "Desk research sources relevant to the linked objective."
                ),
                "priority": question["priority"],
                "preferred_source_types": list(
                    template.get("source_strategy") or ["official statistics"],
                )[:2],
                "timeframe": time_label,
                "geography": geo_label,
                "evidence_expectation": {
                    "nature": "mixed",
                    "required_aspects": [
                        f"objective_coverage_{question['id'].replace('-', '_')}",
                    ],
                    "geography": geo_label,
                    "timeframe": time_label,
                    "requires_quantitative_evidence": False,
                },
            }
        )

    payload = {
        **template,
        "research_questions": questions,
        "information_needs": needs,
        "language": language,
    }
    return json.dumps(payload, indent=2)


def _load_template() -> dict:
    return json.loads(_DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _parse_section(
    text: str,
    *,
    heading: str,
    stop_before: tuple[str, ...] = (),
) -> str:
    marker = f"{heading}\n"
    start = text.find(marker)
    if start == -1:
        return ""
    content = text[start + len(marker) :]
    end = len(content)
    for stop_heading in stop_before:
        stop_marker = f"\n{stop_heading}"
        idx = content.find(stop_marker)
        if idx != -1:
            end = min(end, idx)
    return content[:end].strip()


def _parse_bullet_list(
    text: str,
    *,
    heading: str,
    stop_before: tuple[str, ...] = (),
) -> list[str]:
    section = _parse_section(text, heading=heading, stop_before=stop_before)
    if not section or section == "None specified":
        return []
    items: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _parse_scalar(
    text: str,
    *,
    heading: str,
    stop_before: tuple[str, ...] = (),
) -> str:
    section = _parse_section(text, heading=heading, stop_before=stop_before)
    if not section:
        return ""
    first_line = section.splitlines()[0].strip()
    return first_line
