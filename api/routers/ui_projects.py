from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.ui.presentation import parse_brief_form
from api.ui.project_workspace_facade import build_project_workspace_facade
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from application.quantitative.ui_service import QuantitativeUiError

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter(prefix="/ui/projects", tags=["project-workspace"])
def _facade(request): return build_project_workspace_facade(request.app.state.container)

@router.get("", response_class=HTMLResponse, include_in_schema=False)
def project_list(request: Request): return templates.TemplateResponse(request, "projects/list.html", {"request": request, "view": _facade(request).list_projects()})
@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def project_new(request: Request): return templates.TemplateResponse(request, "projects/new.html", {"request": request, "error": None, "name": ""})
@router.post("", include_in_schema=False)
def project_create(request: Request, name: str = Form("")):
    try:
        project = _facade(request).create_project(name)
        return RedirectResponse(f"/ui/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        return templates.TemplateResponse(request, "projects/new.html", {"request": request, "error": str(exc), "name": name}, status_code=422)
@router.get("/{project_id}", response_class=HTMLResponse, include_in_schema=False)
def project_detail(request: Request, project_id: str):
    try: return templates.TemplateResponse(request, "projects/detail.html", {"request": request, "view": _facade(request).get_workspace(project_id)})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Project not found"}, status_code=404)
@router.get("/{project_id}/desk/new", response_class=HTMLResponse, include_in_schema=False)
def desk_new(request: Request, project_id: str):
    try: return templates.TemplateResponse(request, "projects/desk_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": None})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Project not found"}, status_code=404)
@router.post("/{project_id}/desk", include_in_schema=False)
def desk_create(request: Request, project_id: str, title: str = Form(""), business_question: str = Form(""), objectives: str = Form(""), geography: str = Form(""), timeframe: str = Form(""), market: str = Form(""), target_entities: str = Form(""), constraints: str = Form(""), deliverables: str = Form(""), language: str = Form("en"), context: str = Form(""), known_information: str = Form(""), exclusions: str = Form("")):
    form = {key: value for key, value in locals().items() if key not in {"request", "project_id"}}
    try:
        result = _facade(request).start_desk(project_id, parse_brief_form(form))
        return RedirectResponse(f"/ui/research/{result.workflow_run.id}", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Project not found"}, status_code=404)
    except (ValueError, QuantitativeUiError) as exc:
        return templates.TemplateResponse(request, "projects/desk_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": str(exc)}, status_code=422)
@router.get("/{project_id}/quantitative/new", response_class=HTMLResponse, include_in_schema=False)
def quantitative_new(request: Request, project_id: str):
    try: return templates.TemplateResponse(request, "projects/quantitative_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": None, "submission_key": str(uuid4())})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Project not found"}, status_code=404)
@router.post("/{project_id}/quantitative", include_in_schema=False)
def quantitative_create(request: Request, project_id: str, title: str = Form(""), description: str = Form(""), submission_key: str = Form("")):
    try:
        study = _facade(request).create_quantitative(project_id, title, description, submission_key)
        return RedirectResponse(f"/ui/quantitative/studies/{study.study_id}/overview", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Project not found"}, status_code=404)
    except (ValueError, QuantitativeUiError) as exc:
        return templates.TemplateResponse(request, "projects/quantitative_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": str(exc), "submission_key": submission_key}, status_code=422)
