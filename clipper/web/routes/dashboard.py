"""Dashboard route: aggregated stats."""

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Request

from clipper.web.models import DashboardOut

logger = logging.getLogger("clipper.web.routes.dashboard")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _get_dir_size_gb(path: Path) -> float:
    total = 0
    if not path.exists():
        return 0.0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total / (1024 ** 3)


@router.get("", response_model=DashboardOut)
async def dashboard(request: Request):
    db_web = request.app.state.db_web
    db_clips = request.app.state.db_clips
    wm = request.app.state.worker_manager

    settings = db_web.get_all_settings()
    output_dir = Path(settings.get("output_dir", "./live_output"))
    cap_gb = float(settings.get("max_disk_gb", 20.0))
    spend_cap = float(settings.get("gemini_spend_cap_usd", 10.0))
    gemini_spend = float(settings.get("gemini_spend_usd", 0.0))

    sources = db_web.list_sources()
    all_stats = wm.get_all_stats()
    # Merge runtime stats into source records
    for s in sources:
        ws = all_stats.get(s["id"], {})
        s["status"] = ws.get("status", s.get("status", "idle"))
        s["chunks_done"] = ws.get("chunks_done", 0)
        s["clips_made"] = ws.get("clips_made", 0)

    all_chunks = db_clips.get_all_chunks()
    pending_clips = db_clips.get_pending_clips()
    posts_today_map = db_web.posts_today_count()
    posts_today = sum(posts_today_map.values())

    disk_gb = _get_dir_size_gb(output_dir)
    cap_hit = gemini_spend >= spend_cap and spend_cap > 0

    with db_clips._lock:
        with db_clips._connect() as conn:
            clip_count = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]

    return DashboardOut(
        sources=sources,
        total_chunks=len(all_chunks),
        total_clips=clip_count,
        pending_review=len(pending_clips),
        posts_today=posts_today,
        disk_used_gb=disk_gb,
        disk_cap_gb=cap_gb,
        gemini_spend_usd=gemini_spend,
        gemini_cap_usd=spend_cap,
        cap_hit=cap_hit,
    )
