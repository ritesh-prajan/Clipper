"""Accounts routes: CRUD + test-connection."""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request

from clipper.web.crypto import decrypt_key, encrypt_key, mask_key
from clipper.web.models import AccountCreate, AccountOut, AccountTestResult, AccountUpdate

logger = logging.getLogger("clipper.web.routes.accounts")
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _db_web(request: Request):
    return request.app.state.db_web


def _to_out(acc: dict) -> AccountOut:
    masked = mask_key(acc.get("upload_post_api_key_enc", ""))
    # Try to get actual last-4 from decrypted key (best-effort)
    try:
        raw = decrypt_key(acc["upload_post_api_key_enc"])
        masked = mask_key(raw)
    except Exception:
        pass
    return AccountOut(
        id=acc["id"],
        label=acc["label"],
        upload_post_api_key_masked=masked,
        profile_name=acc.get("profile_name"),
        platforms_enabled=acc.get("platforms_enabled", []),
        enabled=bool(acc.get("enabled", 1)),
        daily_limit_youtube=acc.get("daily_limit_youtube", 10),
        daily_limit_instagram=acc.get("daily_limit_instagram", 10),
        daily_limit_tiktok=acc.get("daily_limit_tiktok", 5),
        min_gap_seconds=acc.get("min_gap_seconds", 300),
        timezone=acc.get("timezone", "UTC"),
        auto_approve=bool(acc.get("auto_approve", 0)),
        caption_suffix=acc.get("caption_suffix", ""),
        created_at=acc["created_at"],
    )


@router.get("", response_model=List[AccountOut])
async def list_accounts(request: Request):
    db_web = _db_web(request)
    accounts = db_web.list_accounts()
    return [_to_out(a) for a in accounts]


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(body: AccountCreate, request: Request):
    db_web = _db_web(request)
    encrypted_key = encrypt_key(body.upload_post_api_key)
    account_id = db_web.create_account(
        label=body.label,
        upload_post_api_key_enc=encrypted_key,
        profile_name=body.profile_name,
        platforms_enabled=body.platforms_enabled,
        enabled=body.enabled,
        daily_limit_youtube=body.daily_limit_youtube,
        daily_limit_instagram=body.daily_limit_instagram,
        daily_limit_tiktok=body.daily_limit_tiktok,
        min_gap_seconds=body.min_gap_seconds,
        timezone=body.timezone,
        auto_approve=body.auto_approve,
        caption_suffix=body.caption_suffix,
    )
    acc = db_web.get_account(account_id)
    return _to_out(acc)


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: str, request: Request):
    db_web = _db_web(request)
    acc = db_web.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return _to_out(acc)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(account_id: str, body: AccountUpdate, request: Request):
    db_web = _db_web(request)
    acc = db_web.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    updates = body.model_dump(exclude_none=True)
    # Encrypt new API key if provided
    if "upload_post_api_key" in updates:
        new_key = updates.pop("upload_post_api_key")
        updates["upload_post_api_key_enc"] = encrypt_key(new_key)

    db_web.update_account(account_id, **updates)
    acc = db_web.get_account(account_id)
    return _to_out(acc)


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: str, request: Request):
    db_web = _db_web(request)
    if not db_web.delete_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found")


@router.post("/{account_id}/test", response_model=AccountTestResult)
async def test_account(account_id: str, request: Request):
    """Test-connection: call GET /api/social/user with this account's API key."""
    db_web = _db_web(request)
    acc = db_web.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    settings = db_web.get_all_settings()
    openshorts_url = settings.get("openshorts_url", "http://localhost:8000")

    try:
        raw_key = decrypt_key(acc["upload_post_api_key_enc"])
    except Exception as e:
        return AccountTestResult(ok=False, error=f"Key decryption failed: {e}")

    try:
        from clipper.openshorts_client import OpenShortsClient
        client = OpenShortsClient(
            base_url=openshorts_url,
            upload_post_api_key=raw_key,
        )
        data = client.get_social_user()
        client.close()
        profiles = data.get("profiles") or []
        return AccountTestResult(ok=True, profiles=profiles)
    except Exception as e:
        err = str(e)
        # Mask any key that might appear in error
        if raw_key and raw_key in err:
            err = err.replace(raw_key, "••••")
        return AccountTestResult(ok=False, error=err)
