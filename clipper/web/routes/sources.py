"""Sources routes: CRUD + start/stop pipeline workers."""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from clipper.web.models import SourceCreate, SourceOut, SourceUpdate

logger = logging.getLogger("clipper.web.routes.sources")
router = APIRouter(prefix="/api/sources", tags=["sources"])


def _db_web(request: Request):
    return request.app.state.db_web


def _wm(request: Request):
    return request.app.state.worker_manager


def _settings(request: Request):
    return request.app.state.db_web.get_all_settings()


@router.get("", response_model=List[SourceOut])
async def list_sources(request: Request):
    db_web = _db_web(request)
    wm = _wm(request)
    sources = db_web.list_sources()
    stats = wm.get_all_stats()
    out = []
    for s in sources:
        worker_stats = stats.get(s["id"], {})
        out.append(SourceOut(
            id=s["id"],
            url=s["url"],
            label=s.get("label"),
            chunk_seconds=s["chunk_seconds"],
            overlap_seconds=s["overlap_seconds"],
            max_clips=s["max_clips"],
            i_own_or_have_permission=bool(s["i_own_or_have_permission"]),
            status=worker_stats.get("status", s["status"]),
            target_account_ids=s["target_account_ids"],
            output_dir=s.get("output_dir"),
            created_at=s["created_at"],
            chunks_done=worker_stats.get("chunks_done", 0),
            clips_made=worker_stats.get("clips_made", 0),
        ))
    return out


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(body: SourceCreate, request: Request):
    db_web = _db_web(request)
    source_id = db_web.create_source(
        url=body.url,
        label=body.label,
        chunk_seconds=body.chunk_seconds,
        overlap_seconds=body.overlap_seconds,
        max_clips=body.max_clips,
        i_own_or_have_permission=body.i_own_or_have_permission,
        target_account_ids=body.target_account_ids,
    )
    source = db_web.get_source(source_id)
    return SourceOut(
        id=source["id"],
        url=source["url"],
        label=source.get("label"),
        chunk_seconds=source["chunk_seconds"],
        overlap_seconds=source["overlap_seconds"],
        max_clips=source["max_clips"],
        i_own_or_have_permission=bool(source["i_own_or_have_permission"]),
        status=source["status"],
        target_account_ids=source["target_account_ids"],
        output_dir=source.get("output_dir"),
        created_at=source["created_at"],
    )


@router.post("/upload", response_model=SourceOut, status_code=201)
async def upload_source_file(
    request: Request,
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
    chunk_seconds: int = Form(90),
    overlap_seconds: int = Form(15),
    max_clips: int = Form(10),
    i_own_or_have_permission: bool = Form(False),
    target_account_ids: str = Form("[]"),
):
    """Upload a local video file to be processed as a source."""
    db_web = _db_web(request)
    output_dir = getattr(request.app.state, "output_dir", Path("./live_output"))
    uploads_dir = Path(output_dir) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    clean_name = re.sub(r"[^\w\.-]", "_", file.filename or "uploaded.mp4")
    file_id = uuid.uuid4().hex[:8]
    dest_path = uploads_dir / f"{file_id}_{clean_name}"

    with open(dest_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            f.write(chunk)

    try:
        parsed_targets = json.loads(target_account_ids)
    except Exception:
        parsed_targets = []

    source_id = db_web.create_source(
        url=str(dest_path.resolve()),
        label=label or file.filename or clean_name,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        max_clips=max_clips,
        i_own_or_have_permission=i_own_or_have_permission,
        target_account_ids=parsed_targets,
    )
    source = db_web.get_source(source_id)
    return SourceOut(
        id=source["id"],
        url=source["url"],
        label=source.get("label"),
        chunk_seconds=source["chunk_seconds"],
        overlap_seconds=source["overlap_seconds"],
        max_clips=source["max_clips"],
        i_own_or_have_permission=bool(source["i_own_or_have_permission"]),
        status=source["status"],
        target_account_ids=source["target_account_ids"],
        output_dir=source.get("output_dir"),
        created_at=source["created_at"],
    )


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: str, request: Request):
    db_web = _db_web(request)
    wm = _wm(request)
    source = db_web.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    stats = wm.get_all_stats().get(source_id, {})
    return SourceOut(
        id=source["id"],
        url=source["url"],
        label=source.get("label"),
        chunk_seconds=source["chunk_seconds"],
        overlap_seconds=source["overlap_seconds"],
        max_clips=source["max_clips"],
        i_own_or_have_permission=bool(source["i_own_or_have_permission"]),
        status=stats.get("status", source["status"]),
        target_account_ids=source["target_account_ids"],
        output_dir=source.get("output_dir"),
        created_at=source["created_at"],
        chunks_done=stats.get("chunks_done", 0),
        clips_made=stats.get("clips_made", 0),
    )


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(source_id: str, body: SourceUpdate, request: Request):
    db_web = _db_web(request)
    if not db_web.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    updates = body.model_dump(exclude_none=True)
    db_web.update_source(source_id, **updates)
    source = db_web.get_source(source_id)
    return SourceOut(
        id=source["id"],
        url=source["url"],
        label=source.get("label"),
        chunk_seconds=source["chunk_seconds"],
        overlap_seconds=source["overlap_seconds"],
        max_clips=source["max_clips"],
        i_own_or_have_permission=bool(source["i_own_or_have_permission"]),
        status=source["status"],
        target_account_ids=source["target_account_ids"],
        output_dir=source.get("output_dir"),
        created_at=source["created_at"],
    )


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str, request: Request):
    db_web = _db_web(request)
    wm = _wm(request)
    wm.stop_source(source_id)
    if not db_web.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")


@router.post("/{source_id}/start")
async def start_source(source_id: str, request: Request):
    db_web = _db_web(request)
    wm = _wm(request)
    source = db_web.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source["i_own_or_have_permission"]:
        raise HTTPException(
            status_code=403,
            detail="Ownership gate: set i_own_or_have_permission=true before starting the pipeline."
        )
    settings = db_web.get_all_settings()
    openshorts_url = settings.get("openshorts_url", "http://localhost:8000")
    auto_approve = bool(settings.get("auto_approve_global", False))
    dry_run = bool(settings.get("dry_run", False))

    from pathlib import Path
    output_dir = Path(source.get("output_dir") or f"./live_output/{source_id}")

    started = wm.start_source(
        source_id=source_id,
        url=source["url"],
        chunk_seconds=source["chunk_seconds"],
        overlap_seconds=source["overlap_seconds"],
        max_clips=source["max_clips"],
        openshorts_url=openshorts_url,
        i_own_or_have_permission=bool(source["i_own_or_have_permission"]),
        auto_approve=auto_approve,
        dry_run=dry_run,
        output_dir=output_dir,
    )
    db_web.update_source(source_id, status="recording" if started else "error")
    return {"started": started}


@router.post("/{source_id}/stop")
async def stop_source(source_id: str, request: Request):
    db_web = _db_web(request)
    wm = _wm(request)
    if not db_web.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    stopped = wm.stop_source(source_id)
    db_web.update_source(source_id, status="stopped")
    return {"stopped": stopped}
