from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from api.ui.session import SESSION_COOKIE, current_ui_user, secure_cookie
from api.routers.ui_research import templates
from application.identity import ProjectRole
from application.operations.status import OperationsStatusService
import os

router = APIRouter(prefix="/ui", tags=["ui-identity"])

def _require_admin():
    user=current_ui_user.get()
    if user is None or user.id != os.environ.get("PILOT_ADMIN_USER_ID"): raise HTTPException(status_code=403, detail="Administrator access required")
    return user

def _safe_next(value: str) -> str:
    return value if value.startswith("/ui/") and not value.startswith("//") else "/ui/projects"

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, next: str = "/ui/projects"):
    if current_ui_user.get() is not None: return RedirectResponse(_safe_next(next), 303)
    return templates.TemplateResponse(request, "identity/login.html", {"request": request, "error": None, "next": _safe_next(next)})

@router.post("/login", include_in_schema=False)
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/ui/projects")):
    service = request.app.state.container.identity_service; user = service.authenticate(email, password)
    if user is None:
        return templates.TemplateResponse(request, "identity/login.html", {"request": request, "error": "Incorrect email or password, or the account is disabled.", "next": _safe_next(next)}, status_code=401)
    token, _ = service.create_session(user); response = RedirectResponse(_safe_next(next), 303)
    response.set_cookie(SESSION_COOKIE, token, max_age=int(service.SESSION_TTL.total_seconds()), httponly=True, secure=secure_cookie(), samesite="lax", path="/ui")
    return response

@router.post("/logout", include_in_schema=False)
def logout(request: Request):
    request.app.state.container.identity_service.logout(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/ui/login", 303); response.delete_cookie(SESSION_COOKIE, path="/ui"); return response

@router.get("/account", response_class=HTMLResponse, include_in_schema=False)
def account(request: Request):
    return templates.TemplateResponse(request, "identity/account.html", {"request": request, "user": current_ui_user.get()})

@router.get("/operations", response_class=HTMLResponse, include_in_schema=False)
def operations(request: Request):
    _require_admin()
    container = request.app.state.container
    service = getattr(container, "operations_status_service", None) or OperationsStatusService(readiness=container.check_readiness)
    return templates.TemplateResponse(request, "identity/operations.html", {"request": request, "snapshot": service.snapshot()})

@router.get("/projects/{project_id}/members", response_class=HTMLResponse, include_in_schema=False)
def members(request: Request, project_id: str):
    service=request.app.state.container.identity_service; user=current_ui_user.get(); service.require(project_id,user.id,owner=True)
    values=[{"membership":m,"user":service.store.get_user(m.user_id)} for m in service.store.list_memberships_for_project(project_id)]
    from api.ui.project_workspace_facade import build_project_workspace_facade
    view=build_project_workspace_facade(request.app.state.container).get_workspace(project_id)
    return templates.TemplateResponse(request,"identity/members.html",{"request":request,"project_id":project_id,"view":view,"members":values,"users":service.store.list_users(),"error":None})

@router.post("/projects/{project_id}/members", include_in_schema=False)
def add_member(request:Request,project_id:str,user_id:str=Form(...),role:str=Form(...)):
    service=request.app.state.container.identity_service; actor=current_ui_user.get(); service.require(project_id,actor.id,owner=True)
    value=ProjectRole(role)
    if value is ProjectRole.OWNER: raise ValueError("New members must start as RESEARCHER or VIEWER")
    service.add_membership(project_id,user_id,value,actor_id=actor.id); return RedirectResponse(f"/ui/projects/{project_id}/members",303)

@router.post("/projects/{project_id}/members/{user_id}/role", include_in_schema=False)
def change_role(request:Request,project_id:str,user_id:str,role:str=Form(...)):
    service=request.app.state.container.identity_service; service.change_role(project_id,user_id,ProjectRole(role),actor_id=current_ui_user.get().id); return RedirectResponse(f"/ui/projects/{project_id}/members",303)

@router.post("/projects/{project_id}/members/{user_id}/remove", include_in_schema=False)
def remove_member(request:Request,project_id:str,user_id:str):
    service=request.app.state.container.identity_service; service.remove_membership(project_id,user_id,actor_id=current_ui_user.get().id); return RedirectResponse(f"/ui/projects/{project_id}/members",303)

@router.get("/admin/users",response_class=HTMLResponse,include_in_schema=False)
def users(request:Request):
    _require_admin();return templates.TemplateResponse(request,"identity/users.html",{"request":request,"users":request.app.state.container.identity_service.store.list_users()})

@router.post("/admin/users",include_in_schema=False)
def create_user(request:Request,email:str=Form(...),display_name:str=Form(...),password:str=Form(...)):
    _require_admin();request.app.state.container.identity_service.create_user(email,display_name,password);return RedirectResponse("/ui/admin/users",303)

@router.post("/admin/users/{user_id}/{action}",include_in_schema=False)
def user_status(request:Request,user_id:str,action:str):
    admin=_require_admin()
    if user_id==admin.id and action=="disable":raise ValueError("Administrator cannot disable the active account")
    service=request.app.state.container.identity_service
    if action=="disable":service.disable_user(user_id)
    elif action=="enable":service.enable_user(user_id)
    else:raise ValueError("Unknown account action")
    return RedirectResponse("/ui/admin/users",303)
