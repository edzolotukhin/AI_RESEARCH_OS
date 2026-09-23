"""Disposable in-memory PF-03 visual acceptance server."""
from __future__ import annotations

from datetime import datetime, timezone

import uvicorn

from api.app import create_fastapi_app
from api.ui.principal import resolve_ui_principal
from application.persistence.records import ArtifactRecord
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.reviews.quality_dimension import QualityDimension, QualityDimensionName, QualityDimensionStatus
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.source import Source
from tests.api.helpers import build_test_container

RUNNING_RUN_ID = "pf03-running-desk"
COMPLETED_RUN_ID = "pf03-completed-desk"
ATTENTION_RUN_ID = "pf03-attention-desk"
DESIGN_ID = "pf03-synthetic-heat-pump-design"


def _fixture_design() -> ResearchDesign:
    objectives = (
        "Оцінити попит і драйвери ринку",
        "Визначити бар’єри входу",
        "Порівняти основні сегменти",
    )
    questions = (
        ("rq-demand", "Як проявляється попит на теплові насоси в Україні та які типи попиту можна розрізнити?", objectives[0]),
        ("rq-drivers", "Які регуляторні, економічні та поведінкові чинники можуть підтримувати попит?", objectives[0]),
        ("rq-segments", "Які сегменти застосування відрізняються потребами, сценаріями купівлі та вимогами до рішення?", objectives[2]),
        ("rq-barriers", "Які бар’єри входу пов’язані з вартістю, монтажем, сервісом, довірою та каналами збуту?", objectives[1]),
        ("rq-comparison", "Які доказово підтверджені відмінності між сегментами мають значення для пріоритетів виходу на ринок?", objectives[2]),
    )
    needs = (
        ("in-demand", "rq-demand", "Ознаки зацікавленості та сценаріїв заміни систем опалення без приписування неперевірених обсягів ринку."),
        ("in-drivers", "rq-drivers", "Документовані стимули, вимоги енергоефективності та мотиви користувачів, що можуть впливати на вибір технології."),
        ("in-segments", "rq-segments", "Порівняльні характеристики житлового, комерційного та нового будівництва: потреби, обмеження й критерії вибору."),
        ("in-barriers", "rq-barriers", "Свідчення про початкову вартість, готовність об’єктів, доступність монтажу, сервісу та консультацій."),
        ("in-comparison", "rq-comparison", "Узгоджені між кількома типами джерел відмінності сегментів, придатні для формування обережних бізнес-імплікацій."),
    )
    expectation = EvidenceExpectation(
        nature=EvidenceNature.QUALITATIVE, geography="Україна", timeframe="2024–2026",
        minimum_independent_sources=1, requires_quantitative_evidence=False,
    )
    return ResearchDesign(
        id=DESIGN_ID,
        research_questions=tuple(ResearchQuestion(item[0], item[1], (item[2],), index, "Окремий аналітичний вимір бізнес-питання.") for index, item in enumerate(questions, 1)),
        information_needs=tuple(InformationNeed(item[0], item[1], item[2], index, ("офіційні матеріали", "галузеві огляди"), "2024–2026", "Україна", expectation) for index, item in enumerate(needs, 1)),
        source_strategy=(
            "Перевіряти офіційні та регуляторні матеріали для контексту політики й вимог.",
            "Зіставляти галузеві огляди, технічні матеріали та дані професійних об’єднань.",
            "Використовувати матеріали каналів збуту й сервісу лише як контекст, чітко відокремлюючи їх від незалежних доказів.",
        ),
        analysis_plan=(
            "Організувати докази за попитом, драйверами, сегментами та бар’єрами.",
            "Зіставити твердження різних типів джерел і позначити прогалини або суперечності.",
            "Формувати висновки лише з простежуваних доказів, а бізнес-імплікації — лише з підтриманих висновків.",
        ),
        deliverable_plan=("Карта попиту та драйверів", "Порівняння сегментів", "Карта бар’єрів входу", "Структурований звіт з обмеженнями"),
        assumptions=("Демонстраційний дизайн ілюструє структуру Desk Research, а не результати реального дослідження.",),
        limitations=("Демонстраційні матеріали не є верифікованими ринковими даними й не придатні для прийняття рішень.",),
        language="uk",
    )


def _brief(title: str) -> ResearchBrief:
    return ResearchBrief(
        title=title,
        business_question="Які фактори визначають привабливість ринку теплових насосів в Україні?",
        objectives=("Оцінити попит і драйвери ринку", "Визначити бар’єри входу", "Порівняти основні сегменти"),
        geography=("Україна",), market="Теплові насоси", timeframe="2024–2026",
        language="uk", context="Рішення щодо виходу постачальника на ринок.",
        deliverables=("Структурований звіт",),
    )


def _create_run(container, owner: str, *, project_id: str, run_id: str, title: str):
    project = container.agency.create_project(title, owner_principal_id=owner, project_id=project_id)
    project.research_brief = _brief(title)
    context = container.agency.start_research(project, run_id=run_id)
    # The visual server is an isolated in-memory fixture. Replace only its
    # generated snapshot; production and historical persisted designs are untouched.
    repository = container.workflow_service._workflow_template_repository
    repository._templates[context.workflow_run.workflow_template_id].research_design_snapshot = _fixture_design()
    return project, context.workflow_run


def _start(run):
    run.ready(); run.start()


def _complete(run):
    _start(run)
    for task in run.tasks:
        task.ready(); task.start(); task.complete()
    run.complete()


def _seed_materials(container, project, run, *, count: int = 6, downstream: bool = True):
    now = datetime.now(timezone.utc).isoformat()
    source_repo = container.source_service._source_repository
    evidence_repo = container.evidence_service._evidence_repository
    finding_repo = container.finding_service._finding_repository
    insight_repo = container.insight_service._insight_repository
    rows = (
        ("Офіційний контекст енергоефективності — синтетичний приклад", "Демонстраційний державний реєстр", "2025-11-18", "rq-drivers", "in-drivers", "Політика енергоефективності може підтримувати інтерес до модернізації опалення, однак сама по собі не підтверджує обсяг попиту.", "У синтетичному матеріалі описано вимоги до енергоефективності та можливі стимули без кількісної оцінки ринку.", "Регуляторний контекст є потенційним драйвером, але його ринковий ефект потребує окремого підтвердження.", "Доказ описує напрям впливу й не містить неперевіреної оцінки масштабу."),
        ("Сценарії модернізації житла — синтетичний огляд", "Демонстраційний аналітичний центр", "2025-09", "rq-demand", "in-demand", "Попит на теплові насоси доцільно розглядати через окремі сценарії: заміну системи, комплексну реновацію та нове будівництво.", "Синтетичний огляд розділяє сценарії придбання за станом будівлі та причиною модернізації.", "Ринковий попит неоднорідний і має аналізуватися за сценаріями придбання, а не як єдиний сегмент.", "Поділ прямо випливає з описаних у доказі сценаріїв і не приписує їм розмір."),
        ("Сегменти застосування теплових насосів — демонстраційна довідка", "Навчальна галузева асоціація", "2025-06-03T00:00:00+00:00", "rq-segments", "in-segments", "Житлові будинки, комерційні об’єкти та нове будівництво мають різні вимоги до інтеграції, потужності й процесу ухвалення рішення.", "Демонстраційна довідка зіставляє типи об’єктів за технічним контекстом і структурою рішення про купівлю.", "Сегментація за типом об’єкта корисна для формування пропозиції та каналів взаємодії.", "Висновок обмежено відмінностями, прямо наведеними у пов’язаному доказі."),
        ("Монтаж і післяпродажний сервіс — синтетична карта екосистеми", "Демонстраційна професійна мережа", "2025", "rq-barriers", "in-barriers", "Доступність кваліфікованого проєктування, монтажу та сервісу може бути критичною умовою впровадження складного обладнання.", "Синтетична карта описує ролі інсталяторів, проєктувальників і сервісних партнерів у клієнтському шляху.", "Сервісна екосистема є окремим бар’єром входу й потребує розвитку разом із продуктовою пропозицією.", "Причинний зв’язок не перебільшується: доказ підтверджує роль екосистеми, а не її фактичну місткість."),
        ("Бар’єри вибору енергоефективного обладнання — демонстраційне дослідження", "Навчальна панель користувачів", "2024-12-10", "rq-barriers", "in-barriers", "Початкова вартість, складність вибору та невизначеність щодо придатності будівлі можуть стримувати рішення про купівлю.", "Синтетичні якісні інтерв’ю групують бар’єри за фінансовими, інформаційними й технічними темами без частот або рейтингів.", "Для зниження бар’єрів потрібна не лише цінова пропозиція, а й зрозуміла консультація щодо придатності рішення.", "Імплікація спирається на три категорії бар’єрів і не видає демонстраційні інтерв’ю за репрезентативне опитування."),
        ("Порівняння шляхів виходу на ринок — синтетичний кейс", "Демонстраційна бізнес-школа", "2024-08", "rq-comparison", "in-comparison", "Сегменти з різною складністю монтажу та структурою закупівлі потребують різних партнерських і сервісних моделей.", "Навчальний кейс зіставляє прямий продаж, партнерський канал і проєктний підхід як альтернативні моделі без заяви про їх фактичну ефективність.", "Пріоритет сегмента слід оцінювати разом із готовністю відповідної партнерської та сервісної моделі.", "Порівняння пов’язує сегмент із моделлю виходу, але не ранжує сегменти без реальних даних."),
    )
    sources=[]; evidence=[]; findings=[]
    for index, row in enumerate(rows[:count], 1):
        title, publisher, published_at, question_id, need_id, statement, excerpt, finding_text, rationale = row
        source=Source(
            id=f"{run.id}-source-{index}", project_id=project.id,
            url=f"https://pf03-demo-{index}.invalid/material", canonical_url=f"https://pf03-demo-{index}.invalid/material",
            title=title, publisher=publisher, source_type="синтетичний матеріал",
            retrieved_at=now, published_at=published_at, language="uk",
            research_question_refs=(question_id,), information_need_refs=(need_id,),
            workflow_run_refs=(run.id,), research_design_refs=(DESIGN_ID,),
        ); source_repo.create(source); sources.append(source)
        item=Evidence(
            id=f"{run.id}-evidence-{index}", project_id=project.id, source_id=source.id,
            source_content_checksum=f"checksum-{index}", workflow_run_id=run.id,
            research_design_id=DESIGN_ID, statement=statement, source_excerpt=excerpt,
            research_question_refs=(question_id,), information_need_refs=(need_id,),
            created_at=now, deduplication_key=f"{run.id}-evidence-{index}",
        ); evidence_repo.create(item); evidence.append(item)
        if not downstream:
            continue
        finding=Finding(
            id=f"{run.id}-finding-{index}", project_id=project.id, workflow_run_id=run.id,
            research_design_id=DESIGN_ID, statement=finding_text,
            rationale=rationale, evidence_refs=(item.id,),
            created_at=now, deduplication_key=f"{run.id}-finding-{index}",
        ); finding_repo.create(finding); findings.append(finding)
    insight_rows = (
        ("Попит варто оцінювати через конкретні сценарії модернізації та типи об’єктів.", "Перед вибором пріоритету потрібна окрема перевірка привабливості кожного сценарію реальними даними.", (2, 3)),
        ("Готовність монтажної й сервісної екосистеми є частиною ринкової пропозиції, а не лише операційним питанням.", "Модель виходу слід перевіряти разом із потенційними локальними партнерами та вимогами до сервісу.", (4, 6)),
        ("Фінансові, інформаційні та технічні бар’єри потребують різних відповідей у клієнтському шляху.", "Наступний етап має перевірити, які бар’єри домінують у кожному цільовому сегменті; демонстраційні матеріали цього не визначають.", (1, 5)),
    )
    for index, (statement, implication, refs) in enumerate(insight_rows, 1):
        linked = tuple(findings[item - 1].id for item in refs if item <= len(findings))
        if not linked:
            continue
        insight_repo.create(Insight(
            id=f"{run.id}-insight-{index}", project_id=project.id, workflow_run_id=run.id,
            research_design_id=DESIGN_ID, statement=statement, implication=implication,
            finding_refs=linked, created_at=now, deduplication_key=f"{run.id}-insight-{index}",
        ))
    return sources,evidence,findings,now


def _seed_report(container, project, run, findings, now, *, verdict: ReviewVerdict):
    report=Report(
        id=f"{run.id}-report", project_id=project.id, workflow_run_id=run.id,
        research_design_id=DESIGN_ID, title="Демонстраційний Desk Research: ринок теплових насосів в Україні",
        language="uk", executive_summary="Це синтетична демонстрація структури Desk Research, а не оцінка реального ринку. Матеріали показують, як сценарії попиту, сегментація, бар’єри та сервісна екосистема можуть бути пов’язані у простежуваному аналізі.",
        sections=(
            ReportSection("section-1","Структура попиту й сегментів","Демонстраційні докази пропонують розрізняти заміну системи, комплексну реновацію та нове будівництво, а також окремо аналізувати житлові й комерційні об’єкти."),
            ReportSection("section-2","Драйвери та бар’єри","Регуляторний контекст може підтримувати інтерес, тоді як вартість, складність вибору, придатність об’єкта та доступність сервісу можуть стримувати рішення."),
            ReportSection("section-3","Імплікації для виходу","Продуктову пропозицію доцільно перевіряти разом із партнерською, монтажною та сервісною моделлю для кожного обраного сегмента."),
        ), limitations=("Усі джерела й твердження створено лише для демонстрації інтерфейсу; вони не є верифікованими ринковими даними.", "Демонстрація не містить оцінок місткості, часток, темпів зростання або рейтингу сегментів."), created_at=now,
        generation_method="fixture-replay", finding_refs=tuple(item.id for item in findings),
        insight_refs=tuple(f"{run.id}-insight-{i}" for i in range(1,4)),
        evidence_refs=tuple(ref for item in findings for ref in item.evidence_refs), citation_registry={},
        deduplication_key=f"{run.id}-report", approval_status="approved" if verdict is ReviewVerdict.APPROVE else "draft",
    ); container.report_query_service._report_repository.create(report)
    issue=() if verdict is ReviewVerdict.APPROVE else (ReviewIssue(
        id=f"{run.id}-issue", issue_type=ReviewIssueType.COVERAGE_GAP,
        severity=ReviewIssueSeverity.MAJOR, message="Потрібне ширше охоплення офіційних статистичних джерел.",
    ),)
    review=ReviewResult(
        id=f"{run.id}-review", project_id=project.id, workflow_run_id=run.id,
        research_design_id=DESIGN_ID, report_id=report.id, review_attempt=1, verdict=verdict,
        quality_dimensions=(QualityDimension(QualityDimensionName.EVIDENCE_SUPPORT,QualityDimensionStatus.PASS if verdict is ReviewVerdict.APPROVE else QualityDimensionStatus.FAIL,"Перевірено"),),
        issues=issue, summary="Демонстраційний звіт структурно узгоджений із синтетичними доказами; це не підтвердження реального ринку." if verdict is ReviewVerdict.APPROVE else "Демонстраційний звіт не схвалено: для фінального результату потрібне ширше покриття.",
        review_method="fixture-replay", created_at=now, deduplication_key=f"{run.id}-review",
        artifact_id=f"{run.id}-artifact" if verdict is ReviewVerdict.APPROVE else None,
    ); container.review_query_service._review_repository.create(review)
    if verdict is ReviewVerdict.APPROVE:
        container.artifact_service.save_artifact(ArtifactRecord(
            id=f"{run.id}-artifact", project_id=project.id, artifact_type="report", title=report.title,
            content="", run_id=run.id, status="approved", report_id=report.id,
        ))


def build_app():
    container=build_test_container(background_execution_mode="embedded")
    owner=resolve_ui_principal(container).principal_id
    completed_project,completed=_create_run(container,owner,project_id="pf03-completed-project",run_id=COMPLETED_RUN_ID,title="PF-03 завершене дослідження")
    _,_,completed_findings,now=_seed_materials(container,completed_project,completed)
    _seed_report(container,completed_project,completed,completed_findings,now,verdict=ReviewVerdict.APPROVE)
    _complete(completed); container.workflow_service.save_workflow_run(completed)

    running_project,running=_create_run(container,owner,project_id="pf03-running-project",run_id=RUNNING_RUN_ID,title="PF-03 дослідження у виконанні")
    _seed_materials(container,running_project,running,count=2,downstream=False); _start(running); running.tasks[0].ready(); running.tasks[0].start(); container.workflow_service.save_workflow_run(running)

    attention_project,attention=_create_run(container,owner,project_id="pf03-attention-project",run_id=ATTENTION_RUN_ID,title="PF-03 дослідження, що потребує уваги")
    _,_,attention_findings,attention_now=_seed_materials(container,attention_project,attention,count=4)
    _seed_report(container,attention_project,attention,attention_findings,attention_now,verdict=ReviewVerdict.REJECT)
    _complete(attention); container.workflow_service.save_workflow_run(attention)
    return create_fastapi_app(container=container)


app=build_app()

if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=8008)
