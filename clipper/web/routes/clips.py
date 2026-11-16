"""Clips routes: list, approve, reject, bulk actions, video streaming."""

import logging
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from clipper.web.models import BulkAction, ClipApprove, ClipOut, ClipUpdate

logger = logging.getLogger("clipper.web.routes.clips")
router = APIRouter(prefix="/api/clips", tags=["clips"])

SAFE_CLIP_ROOTS: list[str] = []  # populated at startup from AppState


def _db(request: Request):
    return request.app.state.db_clips


def _db_web(request: Request):
    return request.app.state.db_web


def _approval(request: Request):
    return request.app.state.approval


def _safe_path(clip_path: str) -> Optional[Path]:
    """Resolve clip path and guard against path traversal."""
    p = Path(clip_path).resolve()
    # Must be under live_output or any configured output dir
    output_base = Path("./live_output").resolve()
    try:
        p.relative_to(output_base)
        return p
    except ValueError:
        pass
    # Also allow any parent that starts with the cwd
    cwd = Path(".").resolve()
    try:
        p.relative_to(cwd)
        return p
    except ValueError:
        return None


def _to_out(clip: dict) -> ClipOut:
    return ClipOut(
        id=clip["id"],
        job_id=clip["job_id"],
        title=clip["title"],
        path=clip["path"],
        approved=clip["approved"],
        posted_platforms=clip.get("posted_platforms", []),
        created_at=clip["created_at"],
    )


@router.get("", response_model=List[ClipOut])
async def list_clips(
    request: Request,
    status: Optional[str] = None,  # "pending" | "approved" | "rejected" | "all"
):
    db = _db(request)
    if status == "pending" or status is None:
        clips = db.get_pending_clips()
    elif status == "approved":
        # approved=1 clips
        with db._lock:
            with db._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM clips WHERE approved=1 ORDER BY created_at DESC"
                ).fetchall()
                import json
                clips = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["posted_platforms"] = json.loads(item.get("posted_platforms") or "[]")
                    except Exception:
                        item["posted_platforms"] = []
                    clips.append(item)
    elif status == "rejected":
        with db._lock:
            with db._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM clips WHERE approved=-1 ORDER BY created_at DESC"
                ).fetchall()
                import json
                clips = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["posted_platforms"] = json.loads(item.get("posted_platforms") or "[]")
                    except Exception:
                        item["posted_platforms"] = []
                    clips.append(item)
    else:
        with db._lock:
            with db._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM clips ORDER BY created_at DESC LIMIT 500"
                ).fetchall()
                import json
                clips = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["posted_platforms"] = json.loads(item.get("posted_platforms") or "[]")
                    except Exception:
                        item["posted_platforms"] = []
                    clips.append(item)
    return [_to_out(c) for c in clips]


@router.get("/{clip_id}", response_model=ClipOut)
async def get_clip(clip_id: str, request: Request):
    db = _db(request)
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _to_out(clip)


@router.patch("/{clip_id}", response_model=ClipOut)
async def update_clip(clip_id: str, body: ClipUpdate, request: Request):
    db = _db(request)
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    updates = body.model_dump(exclude_none=True)
    if "title" in updates:
        db.upsert_clip(
            clip_id=clip["id"],
            job_id=clip["job_id"],
            title=updates["title"],
            path=clip["path"],
            approved=clip["approved"],
            posted_platforms=clip.get("posted_platforms", []),
        )
    return _to_out(db.get_clip(clip_id))


@router.post("/{clip_id}/approve", response_model=ClipOut)
async def approve_clip(clip_id: str, body: ClipApprove, request: Request):
    db = _db(request)
    approval = _approval(request)
    db_web = _db_web(request)
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    ok = approval.approve_clip(clip_id, body.new_title)
    if not ok:
        raise HTTPException(status_code=500, detail="Approval failed")

    # Queue for fan-out if target accounts set
    target_accounts = body.target_account_ids
    if target_accounts is None:
        # Try to get from source defaults (best-effort)
        target_accounts = []

    # Trigger background fan-out for enabled accounts
    if target_accounts:
        import threading
        from clipper.web.fanout import fan_out_post
        settings = db_web.get_all_settings()
        clip_updated = db.get_clip(clip_id)

        def _do_fanout():
            fan_out_post(
                clip_id=clip_id,
                job_id=clip["job_id"],
                clip_title=clip_updated["title"],
                clip_path=Path(clip_updated["path"]),
                account_ids=target_accounts,
                platforms_override=None,
                title_override=None,
                caption_override=None,
                schedule_at=None,
                dry_run=bool(settings.get("dry_run", False)),
                openshorts_url=settings.get("openshorts_url", "http://localhost:8000"),
                db_web=db_web,
                db_clips=db,
            )

        threading.Thread(target=_do_fanout, daemon=True).start()

    return _to_out(db.get_clip(clip_id))


@router.post("/{clip_id}/reject", response_model=ClipOut)
async def reject_clip(clip_id: str, request: Request):
    db = _db(request)
    approval = _approval(request)
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    approval.reject_clip(clip_id)
    return _to_out(db.get_clip(clip_id))


@router.post("/bulk", response_model=List[dict])
async def bulk_action(body: BulkAction, request: Request):
    db = _db(request)
    approval = _approval(request)
    db_web = _db_web(request)
    results = []
    for clip_id in body.clip_ids:
        clip = db.get_clip(clip_id)
        if not clip:
            results.append({"clip_id": clip_id, "ok": False, "error": "not found"})
            continue
        if body.action == "approve":
            ok = approval.approve_clip(clip_id)
        elif body.action == "reject":
            ok = approval.reject_clip(clip_id)
        else:
            ok = False
        results.append({"clip_id": clip_id, "ok": ok})
    return results


@router.get("/{clip_id}/video")
async def stream_video(clip_id: str, request: Request):
    """Stream video with range-request support (no full-file memory load)."""
    db = _db(request)
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    path = _safe_path(clip["path"])
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    content_type = "video/mp4"

    if range_header:
        # Parse "bytes=start-end"
        try:
            byte_range = range_header.replace("bytes=", "")
            start_str, end_str = byte_range.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
        except ValueError:
            start, end = 0, file_size - 1

        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def stream_chunk():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    yield data
                    remaining -= len(data)

        return StreamingResponse(
            stream_chunk(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
            },
        )
    else:
        def stream_full():
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            stream_full(),
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )
