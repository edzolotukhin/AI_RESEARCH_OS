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
    business_question = _parse_scalar(
        prompt.user, heading="Business Question:", stop_before=("Objectives:",),
    )
    methods = _parse_csv_scalar(prompt.user, heading="Selected methods:")
    project_profile = bool(methods)

    if not objectives:
        objectives = ["Complete the stated research goal."]

    geo_label = geography[0] if geography else "Not specified"
    time_label = timeframe if timeframe and timeframe != "Not specified" else "Current period"

    specs = []
    for objective in objectives:
        if project_profile:
            specs.extend(_decompose_objective(
                objective, business_question=business_question, language=language,
            ))
        else:
            question, rationale = _question_text(objective)
            specs.append((question, rationale, "Desk research sources relevant to the linked objective.",
                          "objective_coverage", objective))
    specs = specs[:6]

    questions = [
        {
            "id": f"rq-{index}",
            "question": spec[0],
            "objective_refs": [_objective_for_spec(spec, objectives)],
            "priority": min(index, 5),
            "rationale": spec[1],
        }
        for index, spec in enumerate(specs, start=1)
    ]

    needs = []
    for question, spec in zip(questions, specs):
        needs.append(
            {
                "id": f"in-{question['id']}",
                "research_question_id": question["id"],
                "description": spec[2],
                "priority": question["priority"],
                "preferred_source_types": _source_strategy(
                    methods=methods, language=language, template=template,
                )[:2],
                "timeframe": time_label,
                "geography": geo_label,
                "evidence_expectation": {
                    "nature": _evidence_nature(methods),
                    "required_aspects": [
                        spec[3],
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
        payload.update(_project_level_sections(
            methods=methods, language=language, specs=specs, objectives=objectives,
        ))
    return json.dumps(payload, indent=2)


def _question_text(objective: str) -> tuple[str, str]:
    return (
        f"What evidence is required to address: {objective}?",
        "Derived from brief objective.",
    )


def _decompose_objective(objective: str, *, business_question: str, language: str):
    lowered = objective.casefold()
    uk = language == "uk"
    if any(term in lowered for term in ("розмір", "динамік", "market size", "growth")):
        return [
            _spec(objective, "Який поточний масштаб релевантного ринку?" if uk else "What is the current scale of the relevant market?", "Поточний обсяг і розподіл ключових ринкових показників." if uk else "Current magnitude and distribution of key market measures.", "market_magnitude", uk),
            _spec(objective, "Як змінювався ринок у визначеному часовому горизонті?" if uk else "How has the market changed over the defined timeframe?", "Темпи, напрям і переломні моменти зміни ринку в часі." if uk else "Rate, direction, and turning points of market change over time.", "market_trend", uk),
            _spec(objective, "Які сегменти формують структуру ринку та відрізняються за динамікою?" if uk else "Which segments shape the market and differ in their dynamics?", "Розмір, частка та динаміка релевантних сегментів або категорій." if uk else "Size, share, and trajectory of relevant segments or categories.", "market_structure", uk),
        ]
    if any(term in lowered for term in ("драйвер", "бар'єр", "бар’єр", "driver", "barrier")):
        return [
            _spec(objective, "Які фактори підтримують попит, вибір або використання?" if uk else "Which factors support demand, choice, or usage?", "Поширеність і відносна роль мотиваторів попиту, вибору або використання." if uk else "Prevalence and relative role of demand, choice, or usage drivers.", "demand_drivers", uk),
            _spec(objective, "Які фактори стримують вибір, купівлю або використання?" if uk else "Which factors constrain choice, purchase, or usage?", "Поширеність і значущість функціональних, цінових та поведінкових бар’єрів." if uk else "Prevalence and importance of functional, price, and behavioral barriers.", "adoption_barriers", uk),
            _spec(objective, "Як драйвери та бар’єри відрізняються між релевантними групами?" if uk else "How do drivers and barriers differ across relevant groups?", "Відмінності у драйверах і бар’єрах між релевантними сегментами або групами." if uk else "Differences in drivers and barriers across relevant segments or groups.", "group_differences", uk),
        ]
    subject = objective.rstrip(".?!")
    question = (f"Які характеристики, масштаби та відмінності визначають напрям «{subject}»?" if uk else
                f"Which characteristics, magnitudes, and differences define '{subject}'?")
    need = (f"Конкретні показники, категорії та порівняння, що характеризують «{subject}»." if uk else
            f"Concrete measures, categories, and comparisons that characterize '{subject}'.")
    return [_spec(objective, question, need, "objective_dimensions", uk)]


def _spec(objective, question, need, aspect, uk):
    rationale = ("Питання розкладає ціль на окремий вимір, який можна дослідити." if uk else
                 "The question isolates a researchable dimension of the objective.")
    return (question, rationale, need, aspect, objective)


def _objective_for_spec(spec, objectives):
    return spec[4] if len(spec) > 4 else objectives[0]


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


def _project_level_sections(*, methods: list[str], language: str, specs, objectives) -> dict:
    sources = _source_strategy(methods=methods, language=language, template={})
    uk = language == "uk"
    aspects = {spec[3] for spec in specs}
    if methods == ["QUANTITATIVE"]:
        analysis = _quant_analysis(aspects, uk)
    elif methods == ["DESK"]:
        analysis = _desk_analysis(aspects, uk)
    else:
        analysis = _desk_analysis(aspects, uk) + _quant_analysis(aspects, uk)
    return {
        "source_strategy": sources,
        "analysis_plan": analysis,
        "deliverable_plan": _deliverables(aspects, uk),
        "assumptions": (["Детальний дизайн кожного методу формується у відповідному методному процесі."] if uk else ["Detailed method design is completed in its downstream method flow."]),
        "limitations": (["Проєктний дизайн не визначає детальну методологію виконання окремих методів."] if uk else ["The project design does not specify detailed downstream method execution."]),
    }


def _quant_analysis(aspects, uk):
    items = []
    if aspects & {"market_magnitude", "market_trend", "market_structure"}:
        items.append("Оцінити масштаб, структуру та зміну ключових показників у часі." if uk else "Estimate magnitude, structure, and change in key measures over time.")
    if aspects & {"demand_drivers", "adoption_barriers", "group_differences"}:
        items.append("Порівняти поширеність драйверів і бар’єрів між релевантними групами." if uk else "Compare the prevalence of drivers and barriers across relevant groups.")
    return items or (["Оцінити розподіл ключових показників і відмінності між релевантними групами."] if uk else ["Estimate key-measure distributions and relevant group differences."])


def _desk_analysis(aspects, uk):
    if aspects & {"market_magnitude", "market_trend", "market_structure"}:
        return ["Зіставити оцінки масштабу, структури й динаміки та перевірити їх узгодженість між джерелами." if uk else "Compare market scale, structure, and trend estimates and assess consistency across sources."]
    return ["Зіставити та триангулювати вторинні свідчення за визначеними вимірами." if uk else "Compare and triangulate secondary evidence across the defined dimensions."]


def _deliverables(aspects, uk):
    items = []
    if aspects & {"market_magnitude", "market_trend", "market_structure"}:
        items.append("Оцінка масштабу, структури та динаміки ринку" if uk else "Market scale, structure, and dynamics assessment")
    if aspects & {"demand_drivers", "adoption_barriers", "group_differences"}:
        items.append("Карта драйверів, бар’єрів і відмінностей між групами" if uk else "Driver, barrier, and group-difference map")
    return items or (["Висновки за ключовими вимірами бізнес-питання"] if uk else ["Findings across the key dimensions of the business question"])


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
