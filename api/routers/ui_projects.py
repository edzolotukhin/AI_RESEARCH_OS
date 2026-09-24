from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from api.ui.presentation import parse_brief_form
from api.ui.pdf_csrf import token as pdf_csrf_token, valid as valid_pdf_csrf
from api.ui.project_workspace_facade import build_project_workspace_facade
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError, AuthenticationRequiredError
from application.quantitative.ui_service import QuantitativeUiError

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter(prefix="/ui/projects", tags=["project-workspace"])
def _facade(request): return build_project_workspace_facade(request.app.state.container)

@router.get("", response_class=HTMLResponse, include_in_schema=False)
def project_list(request: Request): return templates.TemplateResponse(request, "projects/list.html", {"request": request, "view": _facade(request).list_projects()})
@router.get("/new", response_class=HTMLResponse, include_in_schema=False)
def project_new(request: Request): return templates.TemplateResponse(request, "projects/new.html", {"request": request, "error": None, "name": "", "selected_methods": ()})
@router.post("", include_in_schema=False)
def project_create(request: Request, name: str = Form(""), selected_methods: list[str] = Form(default=[])):
    try:
        project = _facade(request).create_project(name, selected_methods)
        return RedirectResponse(f"/ui/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        return templates.TemplateResponse(request, "projects/new.html", {"request": request, "error": str(exc), "name": name, "selected_methods": selected_methods}, status_code=422)
@router.get("/{project_id}", response_class=HTMLResponse, include_in_schema=False)
def project_detail(request: Request, project_id: str):
    try: return templates.TemplateResponse(request, "projects/detail.html", {"request": request, "view": _facade(request).get_workspace(project_id)})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)

@router.get("/{project_id}/outputs", response_class=HTMLResponse, include_in_schema=False)
def project_outputs(request: Request, project_id: str):
    try:
        facade = _facade(request)
        return templates.TemplateResponse(request, "projects/outputs.html", {
            "request": request, "view": facade.get_outputs(project_id),
            "catalog": facade.get_report_catalog(project_id),
            "pdf_csrf": lambda method, source_id: pdf_csrf_token(
                request.app.state.container, facade.owner_id, project_id, method, source_id),
            "pdf_error": request.query_params.get("pdf_error") == "1",
            "pptx_error": request.query_params.get("pptx_error") == "1",
            "presentation_enabled": request.app.state.container.project_deliverables_service.presentation_jobs is not None,
            "pptx_csrf": lambda method, source_id: pdf_csrf_token(
                request.app.state.container, facade.owner_id, project_id, method, source_id, "pptx"),
        })
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "Проєкт не знайдено",
        }, status_code=404)


@router.post("/{project_id}/reports/{method}/{source_id}/pdf", include_in_schema=False)
def generate_report_pdf(request: Request, project_id: str, method: str, source_id: str,
                        csrf_token: str = Form("")):
    try:
        facade = _facade(request)
        if not valid_pdf_csrf(request.app.state.container, facade.owner_id,
                              project_id, method, source_id, csrf_token):
            return Response(status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return Response(status_code=403)
        facade.generate_report_pdf(project_id, method, source_id)
        return RedirectResponse(f"/ui/projects/{project_id}/outputs", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "Звіт не знайдено",
        }, status_code=404)
    except AuthenticationRequiredError:
        raise
    except Exception:
        # Never render internal exceptions or report content into the response.
        return RedirectResponse(f"/ui/projects/{project_id}/outputs?pdf_error=1", status_code=303)


@router.get("/{project_id}/reports/{method}/{source_id}", response_class=HTMLResponse,
            include_in_schema=False)
def view_report_source(request: Request, project_id: str, method: str, source_id: str):
    try:
        item = _facade(request).get_report_source(project_id, method, source_id)
        return templates.TemplateResponse(request, "projects/report_source.html", {
            "request": request, "item": item,
        })
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "Звіт не знайдено",
        }, status_code=404)


@router.get("/{project_id}/reports/{method}/{source_id}/pdf/{deliverable_id}", include_in_schema=False)
def download_report_pdf(request: Request, project_id: str, method: str,
                        source_id: str, deliverable_id: str):
    try:
        record, data = _facade(request).download_report_pdf(
            project_id, method, source_id, deliverable_id)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "PDF не знайдено",
        }, status_code=404)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{record.filename}"',
        "Cache-Control": "private, no-store", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/{project_id}/reports/{method}/{source_id}/pptx", include_in_schema=False)
def schedule_report_pptx(request: Request, project_id: str, method: str, source_id: str,
                         csrf_token: str = Form("")):
    try:
        facade = _facade(request)
        if not valid_pdf_csrf(request.app.state.container, facade.owner_id,
                              project_id, method, source_id, csrf_token, "pptx"):
            return Response(status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return Response(status_code=403)
        facade.schedule_presentation(project_id, method, source_id)
        return RedirectResponse(f"/ui/projects/{project_id}/outputs", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "Звіт не знайдено",
        }, status_code=404)
    except AuthenticationRequiredError:
        raise
    except Exception:
        return RedirectResponse(f"/ui/projects/{project_id}/outputs?pptx_error=1", status_code=303)


@router.get("/{project_id}/reports/{method}/{source_id}/pptx/{deliverable_id}", include_in_schema=False)
def download_report_pptx(request: Request, project_id: str, method: str,
                         source_id: str, deliverable_id: str):
    try:
        record, data = _facade(request).download_presentation(
            project_id, method, source_id, deliverable_id)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {
            "request": request, "message": "Презентацію не знайдено",
        }, status_code=404)
    return Response(data, media_type=record.media_type, headers={
        "Content-Disposition": f'attachment; filename="{record.filename}"',
        "Cache-Control": "private, no-store", "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    })

@router.get("/{project_id}/brief", response_class=HTMLResponse, include_in_schema=False)
def project_brief(request: Request, project_id: str):
    try:
        project = _facade(request).project_for_design(project_id)
        return templates.TemplateResponse(request, "projects/brief.html", {"request": request, "project": project, "error": None})
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)

@router.post("/{project_id}/brief", include_in_schema=False)
def project_brief_save(request: Request, project_id: str, title: str = Form(""), business_question: str = Form(""), objectives: str = Form(""), geography: str = Form(""), timeframe: str = Form(""), market: str = Form(""), language: str = Form("uk")):
    form = {key: value for key, value in locals().items() if key not in {"request", "project_id"}}
    facade = _facade(request)
    try:
        facade.save_brief(project_id, parse_brief_form(form))
        return RedirectResponse(f"/ui/projects/{project_id}/design", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except ValueError as exc:
        project = facade.project_for_design(project_id)
        return templates.TemplateResponse(request, "projects/brief.html", {"request": request, "project": project, "error": str(exc)}, status_code=422)

@router.get("/{project_id}/design", response_class=HTMLResponse, include_in_schema=False)
def project_design(request: Request, project_id: str):
    try:
        facade = _facade(request)
        project = facade.project_for_design(project_id)
        view = facade.get_workspace(project_id)
        return templates.TemplateResponse(request, "projects/design.html", {"request": request, "project": project, "view": view, "error": None})
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)

@router.post("/{project_id}/design/generate", include_in_schema=False)
def project_design_generate(request: Request, project_id: str):
    try:
        _facade(request).generate_design(project_id)
        return RedirectResponse(f"/ui/projects/{project_id}/design", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except ValueError as exc:
        facade = _facade(request); project = facade.project_for_design(project_id)
        return templates.TemplateResponse(request, "projects/design.html", {"request": request, "project": project, "view": facade.get_workspace(project_id), "error": str(exc)}, status_code=422)

@router.post("/{project_id}/design/approve", include_in_schema=False)
def project_design_approve(request: Request, project_id: str, design_id: str = Form("")):
    try:
        _facade(request).approve_design(project_id, design_id)
        return RedirectResponse(f"/ui/projects/{project_id}", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except ValueError as exc:
        facade = _facade(request); project = facade.project_for_design(project_id)
        return templates.TemplateResponse(request, "projects/design.html", {"request": request, "project": project, "view": facade.get_workspace(project_id), "error": str(exc)}, status_code=409)

@router.post("/{project_id}/methods", include_in_schema=False)
def project_method_add(request: Request, project_id: str, method: str = Form("")):
    try:
        _facade(request).add_method(project_id, method)
        return RedirectResponse(f"/ui/projects/{project_id}", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)

@router.post("/{project_id}/methods/{method}/remove", include_in_schema=False)
def project_method_remove(request: Request, project_id: str, method: str):
    try:
        _facade(request).remove_method(project_id, method)
        return RedirectResponse(f"/ui/projects/{project_id}", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except ValueError as exc:
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": str(exc)}, status_code=409)

@router.post("/{project_id}/methods/{method}/activate", include_in_schema=False)
def project_method_activate(request: Request, project_id: str, method: str):
    try:
        kind, identity = _facade(request).activate_method(project_id, method)
        target = f"/ui/research/{identity}/overview" if kind == "desk" else f"/ui/quantitative/studies/{identity}/overview"
        return RedirectResponse(target, status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except ValueError as exc:
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": str(exc)}, status_code=409)
@router.get("/{project_id}/desk/new", response_class=HTMLResponse, include_in_schema=False)
def desk_new(request: Request, project_id: str):
    try:
        facade = _facade(request)
        project = facade.project_for_design(project_id)
        if project.selected_methods is not None:
            return RedirectResponse(f"/ui/projects/{project_id}/brief", status_code=303)
        return templates.TemplateResponse(request, "projects/desk_new.html", {"request": request, "view": facade.get_workspace(project_id), "error": None})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
@router.post("/{project_id}/desk", include_in_schema=False)
def desk_create(request: Request, project_id: str, title: str = Form(""), business_question: str = Form(""), objectives: str = Form(""), geography: str = Form(""), timeframe: str = Form(""), market: str = Form(""), target_entities: str = Form(""), constraints: str = Form(""), deliverables: str = Form(""), language: str = Form("en"), context: str = Form(""), known_information: str = Form(""), exclusions: str = Form("")):
    form = {key: value for key, value in locals().items() if key not in {"request", "project_id"}}
    try:
        if _facade(request).project_for_design(project_id).selected_methods is not None:
            return RedirectResponse(f"/ui/projects/{project_id}/brief", status_code=303)
        result = _facade(request).start_desk(project_id, parse_brief_form(form))
        return RedirectResponse(f"/ui/research/{result.workflow_run.id}/overview", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except (ValueError, QuantitativeUiError) as exc:
        return templates.TemplateResponse(request, "projects/desk_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": str(exc)}, status_code=422)
@router.get("/{project_id}/quantitative/new", response_class=HTMLResponse, include_in_schema=False)
def quantitative_new(request: Request, project_id: str):
    try:
        facade = _facade(request)
        project = facade.project_for_design(project_id)
        if project.selected_methods is not None:
            return RedirectResponse(f"/ui/projects/{project_id}", status_code=303)
        return templates.TemplateResponse(request, "projects/quantitative_new.html", {"request": request, "view": facade.get_workspace(project_id), "error": None, "submission_key": str(uuid4())})
    except (AccessDeniedError, EntityNotFoundError): return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
@router.post("/{project_id}/quantitative", include_in_schema=False)
def quantitative_create(request: Request, project_id: str, title: str = Form(""), description: str = Form(""), submission_key: str = Form("")):
    try:
        if _facade(request).project_for_design(project_id).selected_methods is not None:
            return RedirectResponse(f"/ui/projects/{project_id}", status_code=303)
        study = _facade(request).create_quantitative(project_id, title, description, submission_key)
        return RedirectResponse(f"/ui/quantitative/studies/{study.study_id}/overview", status_code=303)
    except (AccessDeniedError, EntityNotFoundError):
        return templates.TemplateResponse(request, "projects/error.html", {"request": request, "message": "Проєкт не знайдено"}, status_code=404)
    except (ValueError, QuantitativeUiError) as exc:
        return templates.TemplateResponse(request, "projects/quantitative_new.html", {"request": request, "view": _facade(request).get_workspace(project_id), "error": str(exc), "submission_key": submission_key}, status_code=422)
