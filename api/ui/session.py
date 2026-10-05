from __future__ import annotations
from contextvars import ContextVar
import os
from urllib.parse import quote
import re
from fastapi import Request
from fastapi.responses import RedirectResponse
from application.identity import current_human_actor_id

SESSION_COOKIE = "ai_research_os_session"
current_ui_user = ContextVar("current_ui_user", default=None)

async def browser_session_middleware(request: Request, call_next):
    path = request.url.path
    public = path in {"/ui/login", "/health", "/ready", "/openapi.json"} or path.startswith("/static/")
    service = getattr(request.app.state.container, "identity_service", None)
    user = service.resolve_session(request.cookies.get(SESSION_COOKIE)) if service else None
    # Explicit injected test containers retain their historical test principal.
    # Production containers never expose or consume a service credential here.
    if path.startswith("/ui") and user is None and getattr(request.app.state.container, "_test_api_key_plaintext", None):
        user = request.app.state.container.authentication_service.authenticate_api_key(
            request.app.state.container._test_api_key_plaintext
        )
    context_token = current_ui_user.set(user)
    actor_token = current_human_actor_id.set(user.id if user is not None and not hasattr(user, "authentication_type") else None)
    request.state.user = user
    try:
        if path.startswith("/ui") and not public and user is None:
            target = path + (("?" + request.url.query) if request.url.query else "")
            return RedirectResponse(f"/ui/login?next={quote(target, safe='/')}", status_code=303)
        if path.startswith("/ui") and not public and user is not None and not hasattr(user, "authentication_type"):
            match=re.match(r"^/ui/projects/([^/]+)",path)
            if match:
                try:
                    service.require(match.group(1),user.id,mutate=request.method not in {"GET","HEAD","OPTIONS"},owner="/members" in path)
                except PermissionError:
                    from fastapi.responses import PlainTextResponse
                    return PlainTextResponse("You don't have access to this project.",status_code=404)
            quant=re.match(r"^/ui/quantitative/studies/([^/]+)",path)
            if quant and request.app.state.container.quantitative_ui_service is not None:
                study=request.app.state.container.quantitative_ui_service.state.find_study_projection(quant.group(1))
                if study is not None:
                    try: service.require(study.project_id,user.id,mutate=request.method not in {"GET","HEAD","OPTIONS"})
                    except PermissionError:
                        from fastapi.responses import PlainTextResponse
                        return PlainTextResponse("You don't have access to this project.",status_code=404)
        if path.startswith("/ui") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse("Request origin is not allowed.", status_code=403)
        return await call_next(request)
    finally:
        current_human_actor_id.reset(actor_token)
        current_ui_user.reset(context_token)

def secure_cookie() -> bool:
    configured = os.environ.get("UI_COOKIE_SECURE", "").casefold()
    if configured: return configured in {"1", "true", "yes"}
    return os.environ.get("APP_ENV", "").casefold() in {"production", "prod"}
