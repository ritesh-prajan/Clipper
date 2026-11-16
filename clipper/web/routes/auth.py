"""Auth routes: login/logout."""

import logging
import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from clipper.web.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    check_credentials,
    create_session,
    is_auth_required,
    verify_session,
)
from clipper.web.models import LoginRequest, LoginResponse

logger = logging.getLogger("clipper.web.routes.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    host = getattr(request.app.state, "bind_host", "127.0.0.1")
    if not is_auth_required(host) and not os.environ.get("CLIPPER_PASSWORD"):
        # Auth not configured — always succeed
        return LoginResponse(ok=True, message="auth_not_configured")

    if not check_credentials(body.password):
        return JSONResponse({"ok": False, "message": "Invalid password"}, status_code=401)

    token = create_session()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        max_age=int(SESSION_TTL),
        path="/",
    )
    return LoginResponse(ok=True, message="Logged in")


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        from clipper.web.auth import _sessions
        _sessions.pop(token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/status")
async def auth_status(request: Request):
    host = getattr(request.app.state, "bind_host", "127.0.0.1")
    required = is_auth_required(host)
    if not required:
        return {"authenticated": True, "auth_required": False}
    token = request.cookies.get(SESSION_COOKIE)
    authenticated = bool(token and verify_session(token))
    return {"authenticated": authenticated, "auth_required": True}
