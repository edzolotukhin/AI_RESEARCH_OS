from __future__ import annotations

import re
from dataclasses import dataclass

from domain.common.exceptions import ValidationError
from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief
from domain.research_method import DESK, QUANTITATIVE


_GENERIC_TOKENS = {
    "what", "which", "evidence", "data", "required", "needed", "address",
    "objective", "goal", "relevant", "establish", "achieve", "derived",
    "що", "які", "яка", "який", "необхідно", "необхідні", "потрібно",
    "дані", "відомості", "свідчення",
    "для", "щодо", "цілі", "мети", "досягнення", "встановити", "релевантні",
}


@dataclass(frozen=True)
class ProjectDesignQualityIssue:
    field: str
    item_id: str
    reason: str


class ProjectDesignQualityError(ValidationError):
    def __init__(self, issues: tuple[ProjectDesignQualityIssue, ...]) -> None:
        self.issues = issues
        super().__init__(
            "Project ResearchDesign contains shallow objective transformations: "
            + "; ".join(f"{item.field}:{item.item_id}" for item in issues)
        )


def validate_project_design_depth(
    brief: ResearchBrief,
    design: ResearchDesign,
    *,
    methods: tuple[str, ...] = (),
) -> None:
    issues: list[ProjectDesignQualityIssue] = []
    objectives = {_normalize(item): item for item in brief.objectives}
    questions = {item.id: item for item in design.research_questions}
    for question in design.research_questions:
        refs = [objectives.get(_normalize(ref), ref) for ref in question.objective_refs]
        if refs and any(_is_mechanical(question.question, ref) for ref in refs):
            issues.append(ProjectDesignQualityIssue(
                "research_question", question.id,
                "question adds no substantive dimension beyond its objective",
            ))
    for need in design.information_needs:
        question = questions.get(need.research_question_id)
        refs = question.objective_refs if question else ()
        if refs and any(_is_mechanical(need.description, ref) for ref in refs):
            issues.append(ProjectDesignQualityIssue(
                "information_need", need.id,
                "need does not specify what must be measured or established",
            ))
    issues.extend(_method_boundary_issues(design, methods))
    if issues:
        raise ProjectDesignQualityError(tuple(issues))


def _method_boundary_issues(
    design: ResearchDesign, methods: tuple[str, ...],
) -> list[ProjectDesignQualityIssue]:
    if not methods:
        return []
    selected = set(methods)
    sources = _searchable(" ".join([
        *design.source_strategy,
        *(item for need in design.information_needs for item in need.preferred_source_types),
    ]))
    full_plan = _searchable(" ".join([
        *design.source_strategy,
        *(item for need in design.information_needs for item in need.preferred_source_types),
        *(item.question for item in design.research_questions),
        *(item.rationale for item in design.research_questions),
        *(item.description for item in design.information_needs),
        *(
            aspect
            for need in design.information_needs
            for aspect in need.evidence_expectation.required_aspects
        ),
        *design.analysis_plan, *design.deliverable_plan,
        *design.assumptions, *design.limitations,
    ]))
    issues: list[ProjectDesignQualityIssue] = []
    desk_markers = (
        "official statistics", "company report", "industry association",
        "reputable media", "secondary source", "public source",
        "офіційн", "компанійн", "галузев", "репутабельн", "вторинн", "публічн",
        "звіт постачальник", "звіти постачальник", "звіт від постачальник",
        "звіти від постачальник", "звіт провайдер", "звіти провайдер",
        "звіт від провайдер", "звіти від провайдер", "reports from provider",
    )
    primary_markers = (
        "respondent", "primary structured", "survey evidence",
        "респондент", "первинні структуровані", "опитуван",
    )
    detailed_quant_markers = (
        "sample size", "quota", "weighting scheme", "questionnaire wording",
        "statistical significance", "regression model", "codebook", "tam sam som",
        "cagr", "розмір вибірки", "квот", "схема зважуван", "формулюванн анкети",
        "статистичн значущ", "statistical significance", "regресі", "регресі",
        "коригувальн ваг", "вагуван", "вибірк", "анкети", "питальник",
        "конджойнт", "gabor granger", "psm", "ціновий модуль", "wtp", "sem",
        "еластичн", "кодбук",
    )
    if selected == {QUANTITATIVE} and any(item in sources for item in desk_markers):
        issues.append(ProjectDesignQualityIssue(
            "source_strategy", "project", "Quantitative-only design introduces Desk evidence",
        ))
    if selected == {DESK} and any(item in sources for item in primary_markers):
        issues.append(ProjectDesignQualityIssue(
            "source_strategy", "project", "Desk-only design introduces respondent evidence",
        ))
    if QUANTITATIVE in selected and any(item in full_plan for item in detailed_quant_markers):
        issues.append(ProjectDesignQualityIssue(
            "method_boundary", "quantitative", "design specifies downstream QZ methodology",
        ))
    if selected == {DESK, QUANTITATIVE}:
        if not any(item in sources for item in desk_markers):
            issues.append(ProjectDesignQualityIssue(
                "source_strategy", "desk", "mixed design omits the Desk evidence role",
            ))
        if not any(item in sources for item in primary_markers):
            issues.append(ProjectDesignQualityIssue(
                "source_strategy", "quantitative", "mixed design omits Quantitative evidence",
            ))
    return issues


def _searchable(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def _is_mechanical(candidate: str, objective: str) -> bool:
    candidate_tokens = _meaningful_tokens(candidate)
    objective_tokens = _meaningful_tokens(objective)
    if not objective_tokens:
        return False
    added = candidate_tokens - objective_tokens
    retained = objective_tokens & candidate_tokens
    return len(retained) >= max(1, len(objective_tokens) - 1) and len(added) <= 1


def _meaningful_tokens(value: str) -> set[str]:
    return {
        _stem(token)
        for token in re.findall(r"[^\W\d_]+", value.casefold(), flags=re.UNICODE)
        if len(token) > 1 and token not in _GENERIC_TOKENS
    }


def _stem(token: str) -> str:
    for suffix in (
        "ування", "ювання", "ними", "ного", "ення", "ання", "ити", "ати",
        "ого", "ому", "ими", "ої", "ій", "ів", "ки", "ку",
        "ing", "ed", "es", "s", "у", "и", "і", "а", "я",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))
