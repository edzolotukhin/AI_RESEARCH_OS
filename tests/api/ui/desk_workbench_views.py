from application.query.desk_workbench_query_service import (
    BoundedText,
    DeskDesignView,
    DeskEvidenceItemView,
    DeskFindingView,
    DeskHeaderView,
    DeskInsightView,
    DeskReportSectionView,
    DeskReportView,
    DeskReviewIssueView,
    DeskReviewView,
    DeskSourceView,
    DeskWorkbenchView,
)


def workbench_view(*, outcome="APPROVED", execution="TERMINAL", malicious=""):
    source = DeskSourceView(
        key="source-1", title=f"Джерело {malicious}", publisher="Видавець",
        domain="example.com", source_type="web", published_at="2026-01-01",
        retrieved_at="2026-01-02", url="https://example.com/source",
        url_display="https://example.com/source", warning=None,
    )
    evidence = DeskEvidenceItemView(
        key="evidence-1", statement=BoundedText(f"Доказ {malicious}"),
        excerpt=BoundedText("Цитата", True), source_key=source.key, source=source,
        research_questions=("Що відбулося?",), information_needs=("Перевірити попит",),
    )
    finding = DeskFindingView(
        key="finding-1", statement=BoundedText("Підтверджений висновок"),
        rationale=BoundedText("Контекст висновку"), evidence=(evidence,),
    )
    review = DeskReviewView(
        verdict="Схвалено" if outcome == "APPROVED" else "Не схвалено",
        verdict_tone="success" if outcome == "APPROVED" else "error",
        summary=BoundedText("Підсумок перевірки"),
        issues=(DeskReviewIssueView("Суттєво", "Бракує посилання", BoundedText("Уточніть джерело")),),
    )
    state = {
        "APPROVED": ("Завершено", "success"),
        "NOT_READY": ("Завершено з обмеженнями", "attention"),
        "QUALITY_REJECTED": ("Потребує уваги", "attention"),
        "EXECUTION_FAILED": ("Помилка", "error"),
    }.get(outcome, ("Виконується", "running"))
    terminal = execution == "TERMINAL"
    return DeskWorkbenchView(
        header=DeskHeaderView("run-a", "project-a", "Проєкт А", state[0], state[1],
                              "Збираються джерела та докази", execution, outcome if terminal else None, terminal),
        design=DeskDesignView(
            "Дослідження ринку", "Яка ринкова можливість?", ("Оцінити попит",),
            ("Україна",), "2026", "B2B", "Контекст", ("Що відбулося?",),
            ("Перевірити попит",), ("Офіційні джерела",), ("Синтез доказів",),
            ("Звіт",), (), (), False,
        ),
        sources=(source,), sources_total=81, evidence=(evidence,), evidence_total=181,
        findings=(finding,) if outcome != "NOT_READY" else (),
        findings_total=1 if outcome != "NOT_READY" else 0,
        insights=(DeskInsightView(BoundedText("Інсайт"), BoundedText("Значення"), (finding.key,)),)
        if outcome == "APPROVED" else (),
        insights_total=1 if outcome == "APPROVED" else 0,
        report=DeskReportView(
            available=outcome in {"APPROVED", "QUALITY_REJECTED"}, title="Звіт",
            executive_summary=BoundedText(f"Резюме {malicious}"),
            sections=(DeskReportSectionView("Розділ", BoundedText("Зміст")),),
            limitations=("Обмеження звіту",), review=review,
        ),
        limitations=("Зібраних матеріалів недостатньо для надійного аналізу.",)
        if outcome == "NOT_READY" else (),
    )
