"""Publishing routes: post, schedule, queue view."""

import logging
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from clipper.web.fanout import fan_out_post
from clipper.web.models import PostOut, PostRequest

logger = logging.getLogger("clipper.web.routes.publishing")
router = APIRouter(prefix="/api/posts", tags=["publishing"])


def _db_web(request: Request):
    return request.app.state.db_web


def _db_clips(request: Request):
    return request.app.state.db_clips


def _settings(request: Request) -> dict:
    return request.app.state.db_web.get_all_settings()


@router.get("", response_model=List[PostOut])
async def list_posts(
    request: Request,
    clip_id: Optional[str] = None,
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
):
    db_web = _db_web(request)
    posts = db_web.list_posts_v2(clip_id=clip_id, account_id=account_id, status=status, limit=limit)
    return [PostOut(**p) for p in posts]


@router.post("/post", response_model=List[dict])
async def post_clip(body: PostRequest, request: Request):
    """Fan out a clip to the specified accounts and platforms."""
    db_web = _db_web(request)
    db_clips = _db_clips(request)
    settings = _settings(request)

    clip = db_clips.get_clip(body.clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip["approved"] != 1:
        raise HTTPException(
            status_code=400,
            detail="Clip must be approved before posting. Use /api/clips/{id}/approve first."
        )

    # Ownership gate: check at least one account matches a source with permission
    # (publisher gate is enforced per-account in fan_out_post)

    effective_dry_run = body.dry_run or bool(settings.get("dry_run", False))
    openshorts_url = settings.get("openshorts_url", "http://localhost:8000")

    # Run in background thread so the response returns quickly
    results_holder = []
    done_event = threading.Event()

    def _do():
        r = fan_out_post(
            clip_id=body.clip_id,
            job_id=clip["job_id"],
            clip_title=clip["title"],
            clip_path=Path(clip["path"]),
            account_ids=body.account_ids,
            platforms_override=body.platforms,
            title_override=body.title_override,
            caption_override=body.caption_override,
            schedule_at=body.schedule_at,
            dry_run=effective_dry_run,
            openshorts_url=openshorts_url,
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=float(settings.get("max_jitter_seconds", 0.0)),
        )
        results_holder.extend(r)
        done_event.set()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    # Wait up to 5s for quick results, then return "queued" status
    done_event.wait(timeout=5.0)
    if results_holder:
        return results_holder
    return [{"status": "queued", "message": "Post jobs dispatched in background"}]


@router.get("/queue", response_model=List[PostOut])
async def get_post_queue(request: Request, limit: int = 100):
    """Return all pending, scheduled, and failed posts."""
    db_web = _db_web(request)
    pending = db_web.list_posts_v2(status="pending", limit=limit // 3)
    scheduled = db_web.list_posts_v2(status="scheduled", limit=limit // 3)
    failed = db_web.list_posts_v2(status="failed", limit=limit // 3)
    all_posts = pending + scheduled + failed
    all_posts.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return [PostOut(**p) for p in all_posts[:limit]]


@router.post("/{post_id}/retry")
async def retry_post(post_id: str, request: Request):
    """Mark a failed post as pending so the scheduler retries it."""
    db_web = _db_web(request)
    posts = db_web.list_posts_v2(limit=1000)
    post = next((p for p in posts if p["id"] == post_id), None)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed posts can be retried")
    db_web.upsert_post_v2(
        clip_id=post["clip_id"],
        account_id=post["account_id"],
        platform=post["platform"],
        status="pending",
        error=None,
    )
    return {"ok": True}
