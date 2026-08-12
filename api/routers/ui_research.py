"""Server-rendered Research UI routes (P1-20.1)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.ui.presentation import (
    OUTCOME_CSS,
    OUTCOME_LABELS,
    PHASE_LABELS,
    PHASE_ORDER,
    brief_form_defaults,
    bounded_text,
    build_result_view_model,
    parse_brief_form,
    phase_index,
    safe_external_url,
    safe_text,
)
from api.ui.research_facade import build_research_ui_facade
from application.persistence.exceptions import (
    AccessDeniedError,
    AuthenticationRequiredError,
    EntityNotFoundError,
)
from domain.common.exceptions import ValidationError
from application.query.research_run_result import ResearchRunResultProjectionError
from application.query.research_status import ResearchExecutionStatus

API_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = API_ROOT / "templates"
STATIC_DIR = API_ROOT / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/ui", tags=["ui"])


def _template_context(request: Request, **extra):
    return {
        "request": request,
        "safe_text": safe_text,
        "bounded_text": bounded_text,
        "safe_external_url": safe_external_url,
        "phase_labels": PHASE_LABELS,
        "phase_order": [phase.value for phase in PHASE_ORDER],
        "outcome_labels": OUTCOME_LABELS,
        "outcome_css": OUTCOME_CSS,
        **extra,
    }


@router.get("", include_in_schema=False)
def ui_root() -> RedirectResponse:
    return RedirectResponse(url="/ui/research/new", status_code=status.HTTP_302_FOUND)


@router.get("/research/new", response_class=HTMLResponse, include_in_schema=False)
def research_new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "research/new.html",
        _template_context(
            request,
            form=brief_form_defaults(),
            form_state="ready",
            error_message=None,
        ),
    )


@router.post("/research", include_in_schema=False)
def research_submit(
    request: Request,
    response: Response,
    title: str = Form(""),
    business_question: str = Form(""),
    objectives: str = Form(""),
    geography: str = Form(""),
    timeframe: str = Form(""),
    market: str = Form(""),
    target_entities: str = Form(""),
    constraints: str = Form(""),
    deliverables: str = Form(""),
    language: str = Form("en"),
    context: str = Form(""),
    known_information: str = Form(""),
    exclusions: str = Form(""),
) -> Response:
    form = {
        "title": title,
        "business_question": business_question,
        "objectives": objectives,
        "geography": geography,
        "timeframe": timeframe,
        "market": market,
        "target_entities": target_entities,
        "constraints": constraints,
        "deliverables": deliverables,
        "language": language,
        "context": context,
        "known_information": known_information,
        "exclusions": exclusions,
    }
    try:
        brief_payload = parse_brief_form(form)
        if not brief_payload["business_question"]:
            raise ValueError("Please enter a business question.")
        facade = build_research_ui_facade(request.app.state.container)
        submission = facade.submit_research(
            brief_payload=brief_payload,
            response=response,
        )
        research_id = submission["research_id"]
        return RedirectResponse(
            url=f"/ui/research/{research_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ValidationError) as exc:
        return templates.TemplateResponse(
            request,
            "research/new.html",
            _template_context(
                request,
                form=form,
                form_state="validation_error",
                error_message=str(exc),
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except AuthenticationRequiredError:
        return templates.TemplateResponse(
            request,
            "research/new.html",
            _template_context(
                request,
                form=form,
                form_state="auth_error",
                error_message="Research UI credentials are not configured.",
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception:
        return templates.TemplateResponse(
            request,
            "research/new.html",
            _template_context(
                request,
                form=form,
                form_state="submission_error",
                error_message="Research could not be submitted. Please try again.",
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/research/{research_id}", response_class=HTMLResponse, include_in_schema=False)
def research_detail_page(request: Request, research_id: str) -> Response:
    try:
        facade = build_research_ui_facade(request.app.state.container)
        status_payload = facade.get_status(research_id)
        detail_payload = None
        if status_payload.get("execution_status") == ResearchExecutionStatus.TERMINAL.value:
            try:
                detail_payload = facade.get_result_detail(research_id)
            except ResearchRunResultProjectionError:
                detail_payload = None
        return templates.TemplateResponse(
            request,
            "research/detail.html",
            _template_context(
                request,
                research_id=research_id,
                status=status_payload,
                detail=build_result_view_model(detail_payload) if detail_payload else None,
                current_phase_index=phase_index(status_payload.get("phase", "QUEUED")),
                page_state="ready",
                error_message=None,
            ),
        )
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(
            request,
            "research/detail.html",
            _template_context(
                request,
                research_id=research_id,
                status=None,
                detail=None,
                current_phase_index=0,
                page_state="not_found",
                error_message="Research not found.",
            ),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except AuthenticationRequiredError:
        return templates.TemplateResponse(
            request,
            "research/detail.html",
            _template_context(
                request,
                research_id=research_id,
                status=None,
                detail=None,
                current_phase_index=0,
                page_state="auth_error",
                error_message="Research UI credentials are not configured.",
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get(
    "/research/{research_id}/status.json",
    include_in_schema=False,
)
def research_status_json(request: Request, research_id: str) -> JSONResponse:
    try:
        facade = build_research_ui_facade(request.app.state.container)
        payload = facade.get_status(research_id)
        return JSONResponse(payload)
    except (AccessDeniedError, EntityNotFoundError):
        return JSONResponse(
            {"error": "research_not_found", "research_id": research_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except AuthenticationRequiredError:
        return JSONResponse(
            {"error": "ui_auth_unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get(
    "/research/{research_id}/detail.json",
    include_in_schema=False,
)
def research_detail_json(request: Request, research_id: str) -> JSONResponse:
    try:
        facade = build_research_ui_facade(request.app.state.container)
        payload = facade.get_result_detail(research_id)
        return JSONResponse(payload)
    except ResearchRunResultProjectionError:
        return JSONResponse(
            {"error": "research_not_terminal", "research_id": research_id},
            status_code=status.HTTP_409_CONFLICT,
        )
    except (AccessDeniedError, EntityNotFoundError):
        return JSONResponse(
            {"error": "research_not_found", "research_id": research_id},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except AuthenticationRequiredError:
        return JSONResponse(
            {"error": "ui_auth_unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def mount_ui_static(app) -> None:
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
