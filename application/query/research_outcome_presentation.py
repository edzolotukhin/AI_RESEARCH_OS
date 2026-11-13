"""Ukrainian presentation only; research outcomes are resolved elsewhere."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchOutcomePresentation:
    label: str
    tone: str
    explanation: str


def present_research_outcome(workflow_status: str, outcome: str | None):
    if workflow_status not in {"completed", "failed", "cancelled"}:
        if workflow_status == "paused":
            return ResearchOutcomePresentation("Потребує уваги", "attention", "Виконання дослідження призупинено.")
        return ResearchOutcomePresentation("Виконується", "running", "Дослідження виконується; остаточний результат ще не визначено.")
    if workflow_status == "cancelled":
        return ResearchOutcomePresentation("Скасовано", "neutral", "Запуск скасовано; наявні матеріали збережено.")
    # A legacy methodological rejection is distinct from a technical failure.
    if outcome == "QUALITY_REJECTED":
        return ResearchOutcomePresentation("Потребує уваги", "attention", "Перевірка якості не схвалила звіт як фінальний результат.")
    if workflow_status == "failed" or outcome in {"FAILED", "EXECUTION_FAILED"}:
        return ResearchOutcomePresentation("Технічна помилка", "error", "Виконання перервано технічною помилкою; наявні матеріали збережено.")
    if outcome in {"COMPLETED", "APPROVED"}:
        return ResearchOutcomePresentation("Завершено", "success", "Дослідницький результат підтверджено. Доступність звіту та файлів показано окремо.")
    if outcome == "PARTIAL":
        return ResearchOutcomePresentation("Завершено з обмеженнями", "attention", "Отримано частину підтверджених результатів; обов’язкові питання залишаються відкритими.")
    if outcome in {"INSUFFICIENT", "NOT_READY"}:
        return ResearchOutcomePresentation("Недостатньо матеріалів", "attention", "Зібраних матеріалів недостатньо для надійного аналізу. Наявні результати доступні для перегляду.")
    return ResearchOutcomePresentation("Результат не визначено", "attention", "Виконання завершено, але дослідницький результат не підтверджено збереженими даними.")


def readiness_reasons(payload, design=None, *, missing_ids=()):
    """Bounded explanation without exposing provider errors or raw payloads."""
    if not isinstance(payload, dict):
        return ()
    labels = {n.id: n.description for n in design.information_needs} if design else {}
    translations = {
        "missing_qualifying_evidence": "Немає придатних доказів.",
        "unavailable_required_observations": "Бракує обов’язкових спостережень або періодів.",
        "missing_required_observation": "Бракує обов’язкових спостережень або періодів.",
        "dependencies_not_ready": "Початкові дані для обчислення або синтезу ще не готові.",
        "metric_unresolved_or_conflicting": "Показники не визначені або несумісні.",
        "geography_unresolved_or_conflicting": "Географія даних не підтверджена або несумісна.",
        "geography_mismatch": "Географія даних не відповідає вимогам.",
        "unit_mismatch": "Одиниці вимірювання несумісні.",
        "zero_denominator": "Відсоткову зміну неможливо обчислити через нульову базу.",
        "insufficient_source_diversity": "Бракує незалежних джерел.",
        "missing_required_aspects": "Не всі обов’язкові аспекти підтверджено.",
        "conflicting_evidence": "Наявні докази суперечать один одному.",
        "assessment_not_current": "Достатність актуальних матеріалів ще не підтверджено.",
    }
    missing = set(missing_ids) | set(payload.get("blocking_information_need_ids", ()))
    reasons = []
    for question in payload.get("research_question_assessments", ()):
        for need in question.get("information_need_assessments", ()):
            diagnostic = need.get("prerequisite_diagnostics") or {}
            if need.get("information_need_kind") == "OUTPUT":
                continue
            if need.get("status") != "sufficient" or need.get("assessment_current") is False:
                missing.add(need.get("information_need_id"))
                reasons.extend(translations.get(code, "Обов’язкові вимоги до матеріалів не виконано.")
                    for code in diagnostic.get("reasons", ()))
    for ref in sorted(ref for ref in missing if isinstance(ref, str)):
        label = labels.get(ref)
        reasons.append("Не підтверджено: " + (label[:200] if label else "обов’язкову інформаційну потребу") + ".")
    if not reasons and payload.get("ready_for_analysis") is False:
        reasons.append("Зібраних матеріалів недостатньо для всіх обов’язкових питань.")
    return tuple(dict.fromkeys(reasons))[:6]
