"""Central, presentation-only humanisation for the Quantitative UI."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from application.query.quantitative_study_views import ProductStatusView

_LABELS = {
    "ONE_WAY": "Одновимірний розподіл",
    "VALID_PERCENTAGE": "Частка валідних відповідей",
    "WEIGHTED_PERCENTAGE": "Зважена частка відповідей",
    "GROUPED_CATEGORY_PERCENTAGE": "Частка об’єднаних категорій",
    "CROSS_TAB_COLUMN_PERCENTAGE": "Частка в групі",
    "CATEGORY_COUNT": "Кількість відповідей",
    "NUMERIC_MEAN": "Середнє значення",
    "NUMERIC_WEIGHTED_MEAN": "Зважене середнє",
    "NUMERIC_MEDIAN": "Медіана",
    "NPS": "Індекс NPS",
    "CUSTOM_INDEX": "Розрахунковий індекс",
    "UNWEIGHTED": "Без зважування",
    "WEIGHTED": "Зі зважуванням",
    "QUANTITATIVE": "Кількісне дослідження",
    "VALID_RESPONSES": "Валідні відповіді",
    "ALL_RESPONSES": "Усі відповіді",
    "ALL_ROWS": "Усі респонденти",
    "SUPPORTED": "Підтверджено",
    "UNVALIDATED": "Не перевірено",
    "VALID": "Перевірено",
    "VALID_WITH_WARNINGS": "Перевірено із зауваженнями",
    "SAV": "Файл SPSS (SAV)",
    "XLSX": "Таблиця Excel (XLSX)",
    "CATEGORICAL": "Категоріальна",
    "NUMERIC": "Числова",
    "IDENTIFIER": "Ідентифікатор",
    "MEASURE": "Показник",
    "DIMENSION": "Розріз",
    "NOMINAL": "Номінальна",
    "ORDINAL": "Порядкова",
    "SCALE": "Шкальна",
}
_PERCENTAGE_TYPES = {
    "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE", "GROUPED_CATEGORY_PERCENTAGE",
    "CROSS_TAB_COLUMN_PERCENTAGE", "ROW_PERCENTAGE", "COLUMN_PERCENTAGE",
}


def canonical_value(value: object, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    raw = value.value if isinstance(value, Enum) else value
    return str(raw)


def humanize(value: object, fallback: str = "—") -> str:
    raw = canonical_value(value, fallback)
    return _LABELS.get(raw.upper(), raw.replace("_", " ").capitalize())


def format_decimal(value: object, places: int = 1) -> str:
    if value is None or value == "":
        return "—"
    decimal = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    rendered = f"{decimal:.{places}f}".replace(".", ",")
    return rendered.rstrip("0").rstrip(",") if places else rendered


def format_statistic(value: object, statistic_type: object) -> str:
    kind = canonical_value(statistic_type, "").upper()
    if value is None or value == "":
        return "—"
    if kind in _PERCENTAGE_TYPES:
        return f"{format_decimal(value, 1)}%"
    if kind in {"CATEGORY_COUNT", "VALID_COUNT", "COUNT"}:
        return f"{Decimal(str(value)):.0f}"
    return format_decimal(value, 2)


def format_base(value: object) -> str:
    if value is None or value == "":
        return "n = —"
    return f"n = {Decimal(str(value)):.0f}"


def finding_statement(text: str) -> str:
    """Remove the exact system-owned context trailer; structured context is shown separately."""
    return text.partition(" [Canonical quantitative context:")[0].strip()


def present_quantitative_status(workflow_status: str, *, terminal_outcome: str = "", scope: str = "study") -> ProductStatusView:
    terminal = terminal_outcome.upper()
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_FINDINGS":
        return ProductStatusView("insufficient", "Недостатньо даних", "warning", "Підтверджених висновків недостатньо.")
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_INSIGHTS":
        return ProductStatusView("partial", "Не сформовано" if scope == "report" else "Частково підтверджено", "warning", "Аналіз завершено, але міжрезультатні інсайти недостатньо підтверджені.")
    if terminal == "COMPLETED_WITH_NO_SUPPORTED_REPORT":
        return ProductStatusView("partial", "Не сформовано", "warning", "Підтриманого автоматичного звіту немає.")
    return {
        "created": ProductStatusView("waiting", "Очікує", "neutral"),
        "waiting": ProductStatusView("waiting", "Очікує", "neutral"),
        "ready": ProductStatusView("ready", "Готово до запуску", "info"),
        "running": ProductStatusView("running", "Виконується", "info"),
        "paused": ProductStatusView("review", "Готово до оцінки", "warning", "Доступна наступна підтверджена дія.", ("resume",)),
        "completed": ProductStatusView("complete", "Завершено", "success"),
        "skipped": ProductStatusView("skipped", "Не потрібно", "neutral"),
        "failed": ProductStatusView("attention", "Потребує уваги", "danger"),
        "cancelled": ProductStatusView("attention", "Потребує уваги", "danger"),
    }.get(workflow_status.lower(), ProductStatusView("unknown", "Очікує", "neutral"))


__all__ = ["canonical_value", "finding_statement", "format_base", "format_decimal", "format_statistic", "humanize", "present_quantitative_status"]