"""Invented Ukrainian report content; no customer or historical study data."""

LONG = ("Синтетичний текст для перевірки перенесення українських абзаців. "
        "Усі назви й числа вигадані; це не дослідницький висновок. ") * 38
URL = "https://example.invalid/very/long/synthetic/source/path/with/many/segments/for/layout/testing"

DESK = {
    "method": "DESK", "project": "Синтетичний проєкт Альфа", "report_id": "desk-synthetic-r3",
    "revision": 3, "composition_id": None, "source_status": "Чернетка",
    "title": "Синтетичний кабінетний звіт",
    "summary": "Вигаданий огляд. Числових або реальних висновків немає.",
    "sections": [
        {"title": "Контекст", "text": "Вигаданий контекст із цитатою [S1].", "citations": ["S1"]},
        {"title": "Довгий розділ", "text": LONG, "citations": ["S1", "S2"]},
        {"title": "Межі огляду", "text": "Жодних реальних джерел не використано.", "citations": []},
    ],
    "tables": [], "charts": [], "limitations": ["Матеріал повністю синтетичний.", "Відсутній необов’язковий розділ."],
    "sources": [{"id": "S1", "title": "Синтетичне джерело один", "url": URL},
                {"id": "S2", "title": "Синтетичне джерело два", "url": "https://example.invalid/two"}],
    "missing": ["optional_research_objective"],
}

QUANT = {
    "method": "QUANTITATIVE", "project": "Синтетичний проєкт Бета", "report_id": "quant-synthetic-report-7",
    "revision": None, "composition_id": "quant-synthetic-composition-7", "source_status": "Прийнятий звіт",
    "title": "Синтетичний кількісний звіт", "summary": "Показники вигадані для тесту формату.",
    "sections": [
        {"title": "Синтетичний показник", "text": "Категорія А: 12 одиниць із бази 40. Це вигадане значення.", "citations": ["Q1"]},
        {"title": "Довгий коментар", "text": LONG, "citations": ["Q1"]},
    ],
    "tables": [
        {"title": "Мала таблиця", "headers": ["Категорія", "Значення", "База", "Одиниця"],
         "rows": [["А", "12", "40", "од."], ["Б", "18", "40", "од."]],
         "source_ref": "quant-result-synthetic-1", "qualification": "Фільтр: усі; без ваг."},
        {"title": "Велика таблиця", "headers": ["Категорія", "Значення", "База", "Одиниця"],
         "rows": [[f"К-{i:02d}", str(i + 2), "40", "од."] for i in range(18)],
         "source_ref": "quant-table-synthetic-2", "qualification": "База 40; тест перенесення рядків."},
    ],
    "charts": [
        {"title": "Підтверджені значення", "categories": ["А", "Б"], "values": [12, 18],
         "unit": "од.", "base": "40", "source_ref": "quant-result-synthetic-1", "eligible": True},
        {"title": "Неповні дані", "categories": ["Х", "Y"], "values": [4, 9],
         "unit": None, "base": None, "source_ref": None, "eligible": False},
    ],
    "limitations": ["Малі синтетичні бази; жодного статистичного узагальнення."],
    "sources": [{"id": "Q1", "title": "Синтетичний запис результату", "url": "https://example.invalid/quant"}],
    "missing": ["insufficient_chart_metadata", "respondent_profile"],
}
