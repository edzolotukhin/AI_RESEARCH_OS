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
    methods = _parse_csv_scalar(prompt.user, heading="Selected methods:")
    project_profile = bool(methods)

    if not objectives:
        objectives = ["Complete the stated research goal."]

    geo_label = geography[0] if geography else "Not specified"
    time_label = timeframe if timeframe and timeframe != "Not specified" else "Current period"

    questions = []
    for index, objective in enumerate(objectives, start=1):
        question, rationale = _question_text(
            objective, language=language, project_profile=project_profile,
        )
        questions.append(
            {
                "id": f"rq-{index}",
                "question": question,
                "objective_refs": [objective],
                "priority": min(index, 5),
                "rationale": rationale,
            }
        )

    needs = []
    for question in questions:
        needs.append(
            {
                "id": f"in-{question['id']}",
                "research_question_id": question["id"],
                "description": _information_need_text(
                    question["objective_refs"][0], methods=methods, language=language,
                ),
                "priority": question["priority"],
                "preferred_source_types": _source_strategy(
                    methods=methods, language=language, template=template,
                )[:2],
                "timeframe": time_label,
                "geography": geo_label,
                "evidence_expectation": {
                    "nature": _evidence_nature(methods),
                    "required_aspects": [
                        f"objective_coverage_{question['id'].replace('-', '_')}",
                    ],
                    "geography": geo_label,
                    "timeframe": time_label,
                    "requires_quantitative_evidence": "QUANTITATIVE" in methods,
                },
            }
        )

    payload = {
        **template,
        "research_questions": questions,
        "information_needs": needs,
        "language": language,
    }
    if project_profile:
        payload.update(_project_level_sections(methods=methods, language=language))
    return json.dumps(payload, indent=2)


def _question_text(objective: str, *, language: str, project_profile: bool) -> tuple[str, str]:
    if not project_profile:
        return (
            f"What evidence is required to address: {objective}?",
            "Derived from brief objective.",
        )
    if language == "uk":
        return (
            f"Що необхідно встановити для досягнення цілі «{objective}»?",
            "Питання безпосередньо пов’язане з ціллю дослідження.",
        )
    return (
        f"What must the research establish to achieve the objective '{objective}'?",
        "The question directly supports the research objective.",
    )


def _information_need_text(objective: str, *, methods: list[str], language: str) -> str:
    if language == "uk":
        if methods == ["QUANTITATIVE"]:
            return f"Вимірювані дані респондентів, необхідні для цілі «{objective}»."
        if methods == ["DESK"]:
            return f"Вторинні дані та відкриті свідчення, релевантні цілі «{objective}»."
        return f"Вторинні джерела й структуровані вимірювання для цілі «{objective}»."
    if methods == ["QUANTITATIVE"]:
        return f"Measurable respondent evidence required for the objective '{objective}'."
    if methods == ["DESK"]:
        return f"Secondary and open evidence relevant to the objective '{objective}'."
    if methods:
        return f"Secondary evidence and structured measurement for the objective '{objective}'."
    return "Desk research sources relevant to the linked objective."


def _source_strategy(*, methods: list[str], language: str, template: dict) -> list[str]:
    if not methods:
        return list(template.get("source_strategy") or ["official statistics"])
    uk = language == "uk"
    if methods == ["QUANTITATIVE"]:
        return (["Первинні структуровані дані респондентів"] if uk else
                ["primary structured respondent evidence"])
    desk = (["Релевантні офіційні та галузеві відкриті джерела"] if uk else
            ["relevant official and industry open sources"])
    if methods == ["DESK"]:
        return desk
    quant = (["Первинні структуровані дані респондентів"] if uk else
             ["primary structured respondent evidence"])
    return [*desk, *quant]


def _project_level_sections(*, methods: list[str], language: str) -> dict:
    sources = _source_strategy(methods=methods, language=language, template={})
    uk = language == "uk"
    if methods == ["QUANTITATIVE"]:
        analysis = ["Оцінити ключові показники та відмінності між релевантними групами."] if uk else ["Assess key measures and relevant group differences."]
    elif methods == ["DESK"]:
        analysis = ["Зіставити та узагальнити релевантні вторинні свідчення."] if uk else ["Compare and synthesize relevant secondary evidence."]
    else:
        analysis = ["Окремо спланувати контекстний аналіз і кількісне вимірювання."] if uk else ["Plan contextual analysis and quantitative measurement as distinct streams."]
    return {
        "source_strategy": sources,
        "analysis_plan": analysis,
        "deliverable_plan": (["Підсумок результатів за цілями дослідження"] if uk else ["Research objective findings summary"]),
        "assumptions": (["Детальний дизайн кожного методу формується у відповідному методному процесі."] if uk else ["Detailed method design is completed in its downstream method flow."]),
        "limitations": (["Проєктний дизайн не визначає детальну методологію виконання окремих методів."] if uk else ["The project design does not specify detailed downstream method execution."]),
    }


def _evidence_nature(methods: list[str]) -> str:
    if methods == ["QUANTITATIVE"]:
        return "quantitative"
    if methods == ["DESK"]:
        return "qualitative"
    return "mixed"


def _parse_csv_scalar(text: str, *, heading: str) -> list[str]:
    value = ""
    for line in text.splitlines():
        if line.startswith(heading):
            value = line[len(heading):].strip()
            break
    return [item.strip() for item in value.split(",") if item.strip()]


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
