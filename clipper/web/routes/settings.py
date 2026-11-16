"""Settings routes."""

import logging
import os

from fastapi import APIRouter, Request

from clipper.web.models import SettingsOut, SettingsUpdate

logger = logging.getLogger("clipper.web.routes.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])

_DEFAULTS = {
    "openshorts_url": "http://localhost:8000",
    "max_disk_gb": 20.0,
    "auto_approve_global": False,
    "dry_run": False,
    "gemini_spend_cap_usd": 10.0,
    "output_dir": "./live_output",
    "bind_host": "127.0.0.1",
}


def _db_web(request: Request):
    return request.app.state.db_web


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request):
    db_web = _db_web(request)
    s = db_web.get_all_settings()
    has_password = bool(os.environ.get("CLIPPER_PASSWORD") or s.get("auth_password_hash"))
    return SettingsOut(
        openshorts_url=s.get("openshorts_url", _DEFAULTS["openshorts_url"]),
        max_disk_gb=float(s.get("max_disk_gb", _DEFAULTS["max_disk_gb"])),
        auto_approve_global=bool(s.get("auto_approve_global", _DEFAULTS["auto_approve_global"])),
        dry_run=bool(s.get("dry_run", _DEFAULTS["dry_run"])),
        gemini_spend_cap_usd=float(s.get("gemini_spend_cap_usd", _DEFAULTS["gemini_spend_cap_usd"])),
        has_password=has_password,
        output_dir=str(s.get("output_dir", _DEFAULTS["output_dir"])),
        bind_host=str(s.get("bind_host", _DEFAULTS["bind_host"])),
    )


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, request: Request):
    db_web = _db_web(request)
    updates = body.model_dump(exclude_none=True)

    # Handle password change separately
    if "auth_password" in updates:
        new_pw = updates.pop("auth_password")
        if new_pw:
            import hashlib
            pw_hash = hashlib.sha256(new_pw.encode()).hexdigest()
            db_web.set_setting("auth_password_hash", pw_hash)
            os.environ["CLIPPER_PASSWORD"] = new_pw
        else:
            db_web.set_setting("auth_password_hash", "")
            os.environ.pop("CLIPPER_PASSWORD", None)

    for key, val in updates.items():
        db_web.set_setting(key, val)

    return await get_settings(request)
