"""Bounded, read-only projections for the Desk Research workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from urllib.parse import urlparse

from application.query.research_run_result import ResearchRunResultProjectionError
from application.query.research_status import ResearchExecutionStatus


COLLECTION_LIMIT = 50
TEXT_LIMIT = 4_000
EXCERPT_LIMIT = 1_200


@dataclass(frozen=True)
class BoundedText:
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class DeskHeaderView:
    run_id: str
    project_id: str
    project_name: str
    state: str
    state_tone: str
    activity: str
    execution_status: str
    outcome: str | None
    is_terminal: bool


@dataclass(frozen=True)
class DeskDesignView:
    title: str
    business_question: str
    objectives: tuple[str, ...]
    geography: tuple[str, ...]
    timeframe: str
    market: str
    context: str
    research_questions: tuple[str, ...]
    information_needs: tuple[str, ...]
    source_strategy: tuple[str, ...]
    analysis_plan: tuple[str, ...]
    deliverable_plan: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    historical_fallback: bool


@dataclass(frozen=True)
class DeskSourceView:
    key: str
    title: str
    publisher: str
    domain: str
    source_type: str
    published_at: str | None
    retrieved_at: str
    url: str | None
    url_display: str
    warning: str | None


@dataclass(frozen=True)
class DeskEvidenceItemView:
    key: str
    statement: BoundedText
    excerpt: BoundedText
    source_key: str | None
    source: DeskSourceView | None
    research_questions: tuple[str, ...]
    information_needs: tuple[str, ...]


@dataclass(frozen=True)
class DeskFindingView:
    key: str
    statement: BoundedText
    rationale: BoundedText
    evidence: tuple[DeskEvidenceItemView, ...]


@dataclass(frozen=True)
class DeskInsightView:
    statement: BoundedText
    implication: BoundedText
    finding_keys: tuple[str, ...]


@dataclass(frozen=True)
class DeskReportSectionView:
    title: str
    content: BoundedText


@dataclass(frozen=True)
class DeskReviewIssueView:
    severity: str
    label: str
    message: BoundedText


@dataclass(frozen=True)
class DeskReviewView:
    verdict: str
    verdict_tone: str
    summary: BoundedText
    issues: tuple[DeskReviewIssueView, ...]


@dataclass(frozen=True)
class DeskReportView:
    available: bool
    title: str
    executive_summary: BoundedText
    sections: tuple[DeskReportSectionView, ...]
    limitations: tuple[str, ...]
    review: DeskReviewView | None


@dataclass(frozen=True)
class DeskWorkbenchView:
    header: DeskHeaderView
    design: DeskDesignView
    sources: tuple[DeskSourceView, ...]
    sources_total: int
    evidence: tuple[DeskEvidenceItemView, ...]
    evidence_total: int
    findings: tuple[DeskFindingView, ...]
    findings_total: int
    insights: tuple[DeskInsightView, ...]
    insights_total: int
    report: DeskReportView
    limitations: tuple[str, ...]


class DeskWorkbenchQueryService:
    """Projects canonical Desk state without writes or cross-run joins."""

    def __init__(self, *, container) -> None:
        self._container = container

    def get(self, run_id: str, *, project) -> DeskWorkbenchView:
        run = self._container.workflow_service.get_workflow_run(run_id)
        if run.project_id != project.id:
            raise ValueError("Run and Project scope do not match")
        status = self._container.research_status_query_service.get_status(run_id)
        template = self._container.workflow_service.get_template(
            run.workflow_template_id,
        )

        source_entities = self._container.source_service.list_sources_for_run(
            run_id, project_id=project.id,
        )
        evidence_entities = self._container.evidence_service.list_evidence_for_project(
            project.id, workflow_run_id=run_id,
        )
        finding_entities = self._container.finding_service.list_findings_for_project(
            project.id, workflow_run_id=run_id,
        )
        insight_entities = self._container.insight_service.list_insights_for_project(
            project.id, workflow_run_id=run_id,
        )
        reports = self._container.report_query_service.list_reports_for_project(
            project.id, workflow_run_id=run_id,
        )
        reviews = self._container.review_query_service.list_reviews_for_project(
            project.id, workflow_run_id=run_id,
        )

        source_entities = sorted(source_entities, key=lambda item: (item.title.lower(), item.id))
        evidence_entities = sorted(evidence_entities, key=lambda item: (item.created_at, item.id))
        finding_entities = sorted(finding_entities, key=lambda item: (item.created_at, item.id))
        insight_entities = sorted(insight_entities, key=lambda item: (item.created_at, item.id))

        shown_sources = source_entities[:COLLECTION_LIMIT]
        source_views = tuple(self._source(item, index) for index, item in enumerate(shown_sources))
        source_by_id = {item.id: source_views[index] for index, item in enumerate(shown_sources)}
        question_labels, need_labels = self._design_labels(template)
        shown_evidence = evidence_entities[:COLLECTION_LIMIT]
        evidence_views = tuple(
            self._evidence(item, index, source_by_id, question_labels, need_labels)
            for index, item in enumerate(shown_evidence)
        )
        evidence_by_id = {
            item.id: evidence_views[index] for index, item in enumerate(shown_evidence)
        }
        finding_views = tuple(
            self._finding(item, index, evidence_by_id)
            for index, item in enumerate(finding_entities[:COLLECTION_LIMIT])
        )
        insight_views = tuple(
            self._insight(item, finding_entities)
            for item in insight_entities[:COLLECTION_LIMIT]
        )

        limitations: tuple[str, ...] = ()
        outcome = status.product_outcome.value if status.product_outcome else None
        if status.execution_status is ResearchExecutionStatus.TERMINAL:
            try:
                result = self._container.research_run_result_query_service.get_for_run(run_id)
                limitations = tuple(self._limitation(item) for item in result.limitations)
            except ResearchRunResultProjectionError:
                pass

        header = self._header(run, project, status, outcome)
        return DeskWorkbenchView(
            header=header,
            design=self._design(template),
            sources=source_views,
            sources_total=len(source_entities),
            evidence=evidence_views,
            evidence_total=len(evidence_entities),
            findings=finding_views,
            findings_total=len(finding_entities),
            insights=insight_views,
            insights_total=len(insight_entities),
            report=self._report(reports, reviews),
            limitations=limitations,
        )

    @staticmethod
    def _bound(value: str | None, limit: int = TEXT_LIMIT) -> BoundedText:
        text = str(value or "")
        if len(text) <= limit:
            return BoundedText(text)
        return BoundedText(text[:limit].rstrip() + "…", True)

    @staticmethod
    def _limitation(value: str) -> str:
        labels = {
            "insufficient_research": "Зібраних матеріалів недостатньо для надійного аналізу.",
            "evidence_remediation_budget_exhausted": "Не всі інформаційні потреби вдалося підтвердити в межах цього запуску.",
            "downstream_reserve_exhausted": "Дослідження завершилося до формування повного набору результатів.",
            "sufficiency_budget_exhausted": "Перевірка достатності виявила непідтверджені інформаційні потреби.",
        }
        text = str(value or "").strip()
        if text in labels:
            return labels[text]
        if text and (" " in text or "_" not in text):
            return text
        return "Дослідження завершено з додатковими обмеженнями."

    @staticmethod
    def _header(run, project, status, outcome: str | None) -> DeskHeaderView:
        phase_labels = {
            "QUEUED": "Очікує на початок роботи",
            "PLANNING": "Готується план виконання",
            "RESEARCHING": "Збираються джерела та докази",
            "EVALUATING": "Перевіряється достатність доказів",
            "ANALYZING": "Формуються висновки та інсайти",
            "WRITING": "Готується звіт",
            "REVIEWING": "Виконується перевірка якості",
            "COMPLETED": "Дослідження завершено",
        }
        if run.status.value == "cancelled":
            state, tone = "Скасовано", "neutral"
        elif outcome == "APPROVED":
            state, tone = "Завершено", "success"
        elif outcome == "NOT_READY":
            state, tone = "Завершено з обмеженнями", "attention"
        elif outcome == "QUALITY_REJECTED":
            state, tone = "Потребує уваги", "attention"
        elif outcome == "EXECUTION_FAILED" or run.status.value == "failed":
            state, tone = "Помилка", "error"
        elif run.status.value == "completed":
            state, tone = "Завершено", "success"
        elif run.status.value == "paused":
            state, tone = "Потребує уваги", "attention"
        elif status.execution_status is ResearchExecutionStatus.RUNNING:
            state, tone = "Виконується", "running"
        else:
            state, tone = "У черзі", "neutral"
        return DeskHeaderView(
            run_id=run.id,
            project_id=project.id,
            project_name=project.name,
            state=state,
            state_tone=tone,
            activity=phase_labels.get(status.phase.value, "Стан дослідження оновлюється"),
            execution_status=status.execution_status.value,
            outcome=outcome,
            is_terminal=status.execution_status is ResearchExecutionStatus.TERMINAL,
        )

    @staticmethod
    def _design(template) -> DeskDesignView:
        brief = template.research_brief_snapshot
        design = template.research_design_snapshot
        return DeskDesignView(
            title=brief.title if brief else template.name,
            business_question=brief.business_question if brief else "",
            objectives=brief.objectives if brief else (),
            geography=brief.geography if brief else (),
            timeframe=brief.timeframe if brief else "",
            market=brief.market if brief else "",
            context=brief.context if brief else "",
            research_questions=tuple(q.question for q in design.research_questions) if design else (),
            information_needs=tuple(n.description for n in design.information_needs) if design else (),
            source_strategy=design.source_strategy if design else (),
            analysis_plan=design.analysis_plan if design else (),
            deliverable_plan=design.deliverable_plan if design else (),
            assumptions=design.assumptions if design else (),
            limitations=design.limitations if design else (),
            historical_fallback=brief is None or design is None,
        )

    @staticmethod
    def _design_labels(template):
        design = template.research_design_snapshot
        if design is None:
            return {}, {}
        return (
            {item.id: item.question for item in design.research_questions},
            {item.id: item.description for item in design.information_needs},
        )

    @staticmethod
    def _source(source, index: int) -> DeskSourceView:
        parsed = urlparse(source.url or "")
        safe_url = source.url if parsed.scheme in {"http", "https"} and parsed.netloc else None
        warning = None
        if source.retrieval_status.value == "truncated":
            warning = "Матеріал отримано частково"
        elif source.retrieval_status.value in {"failed", "unsupported"}:
            warning = "Матеріал не вдалося повністю опрацювати"
        return DeskSourceView(
            key=f"source-{index + 1}", title=source.title or parsed.netloc or "Джерело",
            publisher=source.publisher, domain=parsed.netloc,
            source_type=source.source_type,
            published_at=DeskWorkbenchQueryService._display_date(source.published_at),
            retrieved_at=DeskWorkbenchQueryService._display_date(source.retrieved_at) or "Дата не вказана",
            url=safe_url, url_display=source.url or "", warning=warning,
        )

    @staticmethod
    def _display_date(value) -> str | None:
        """Format a stored date for Ukrainian UI without changing the source value."""
        if value is None or not str(value).strip():
            return None
        text = str(value).strip()
        months = (
            "січня", "лютого", "березня", "квітня", "травня", "червня",
            "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
        )
        month_names = (
            "січень", "лютий", "березень", "квітень", "травень", "червень",
            "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
        )
        if re.fullmatch(r"\d{4}", text):
            return f"{text} р."
        match = re.fullmatch(r"(\d{4})-(\d{2})", text)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            return f"{month_names[month - 1]} {year} р." if 1 <= month <= 12 else "Дата не вказана"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                return "Дата не вказана"
        return f"{parsed.day} {months[parsed.month - 1]} {parsed.year} р."

    def _evidence(self, evidence, index, source_by_id, question_labels, need_labels):
        return DeskEvidenceItemView(
            key=f"evidence-{index + 1}",
            statement=self._bound(evidence.statement),
            excerpt=self._bound(evidence.source_excerpt, EXCERPT_LIMIT),
            source_key=(source_by_id[evidence.source_id].key if evidence.source_id in source_by_id else None),
            source=source_by_id.get(evidence.source_id),
            research_questions=tuple(question_labels[item] for item in evidence.research_question_refs if item in question_labels),
            information_needs=tuple(need_labels[item] for item in evidence.information_need_refs if item in need_labels),
        )

    def _finding(self, finding, index, evidence_by_id):
        return DeskFindingView(
            key=f"finding-{index + 1}", statement=self._bound(finding.statement),
            rationale=self._bound(finding.rationale),
            evidence=tuple(evidence_by_id[item] for item in finding.evidence_refs if item in evidence_by_id),
        )

    def _insight(self, insight, finding_entities):
        key_by_id = {item.id: f"finding-{index + 1}" for index, item in enumerate(finding_entities[:COLLECTION_LIMIT])}
        return DeskInsightView(
            statement=self._bound(insight.statement), implication=self._bound(insight.implication),
            finding_keys=tuple(key_by_id[item] for item in insight.finding_refs if item in key_by_id),
        )

    def _report(self, reports, reviews) -> DeskReportView:
        if not reports:
            return DeskReportView(False, "", BoundedText(""), (), (), None)
        report = max(reports, key=lambda item: (item.revision_number, item.created_at, item.id))
        related = [item for item in reviews if item.report_id == report.id]
        review = max(related, key=lambda item: (item.review_attempt, item.created_at, item.id)) if related else None
        return DeskReportView(
            available=True, title=report.title,
            executive_summary=self._bound(report.executive_summary),
            sections=tuple(DeskReportSectionView(item.title, self._bound(item.content)) for item in report.sections),
            limitations=tuple(report.limitations), review=self._review(review) if review else None,
        )

    def _review(self, review) -> DeskReviewView:
        verdicts = {
            "approve": ("Схвалено", "success"),
            "revise": ("Потребує доопрацювання", "attention"),
            "reject": ("Не схвалено", "error"),
        }
        issue_labels = {
            "unsupported_claim": "Непідтверджене твердження", "missing_citation": "Бракує посилання",
            "coverage_gap": "Прогалина в охопленні", "contradiction": "Суперечність",
            "inconsistent_analysis": "Непослідовний аналіз", "missing_limitation": "Не зазначено обмеження",
            "brief_mismatch": "Невідповідність брифу", "structure_issue": "Проблема структури",
        }
        label, tone = verdicts.get(review.verdict.value, ("Перевірено", "neutral"))
        return DeskReviewView(
            verdict=label, verdict_tone=tone, summary=self._bound(review.summary),
            issues=tuple(DeskReviewIssueView(
                severity="Суттєво" if item.severity.value == "major" else "Зауваження",
                label=issue_labels.get(item.issue_type.value, "Зауваження перевірки"),
                message=self._bound(item.message),
            ) for item in review.issues[:COLLECTION_LIMIT]),
        )
