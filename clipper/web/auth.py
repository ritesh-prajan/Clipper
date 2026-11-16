"""Optional single-user password login middleware.

When CLIPPER_PASSWORD env var is set (or the 'auth_password_hash' setting
is non-empty), every request to non-static, non-login paths must present a
valid session cookie.

If the server is bound to a non-localhost address, password auth is REQUIRED
regardless of the setting.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Callable, Optional

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("clipper.web.auth")

# Session store: token -> expiry_timestamp
_sessions: dict[str, float] = {}
SESSION_TTL = 86400.0  # 24 hours
SESSION_COOKIE = "clipper_session"

# Public paths that never need auth
_PUBLIC_PREFIXES = ("/auth/", "/assets/", "/favicon.ico", "/")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _get_configured_hash() -> Optional[str]:
    pw = os.environ.get("CLIPPER_PASSWORD", "")
    if pw:
        return _hash_password(pw)
    return None


def is_auth_required(host: str) -> bool:
    """Return True if authentication is required based on host binding."""
    if os.environ.get("CLIPPER_PASSWORD"):
        return True
    # Required for non-localhost binding
    if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return True
    return False


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    _prune_sessions()
    return token


def verify_session(token: str) -> bool:
    exp = _sessions.get(token)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(token, None)
        return False
    return True


def _prune_sessions() -> None:
    now = time.time()
    expired = [t for t, exp in _sessions.items() if exp < now]
    for t in expired:
        _sessions.pop(t, None)


def check_credentials(password: str) -> bool:
    pw_hash = _get_configured_hash()
    if not pw_hash:
        return False
    return hmac.compare_digest(_hash_password(password), pw_hash)


async def auth_middleware(request: Request, call_next: Callable) -> Response:
    """ASGI middleware: enforce session cookie on protected routes."""
    host = request.app.state.bind_host if hasattr(request.app.state, "bind_host") else "127.0.0.1"

    if not is_auth_required(host):
        return await call_next(request)

    path = request.url.path
    # Allow login endpoint and static files
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES) and path != "/":
        # Allow /assets/* always
        if path.startswith("/assets/") or path.startswith("/auth/"):
            return await call_next(request)

    # API endpoints need auth
    if path.startswith("/api/") or path.startswith("/sse"):
        token = request.cookies.get(SESSION_COOKIE)
        if not token or not verify_session(token):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)

    return await call_next(request)
