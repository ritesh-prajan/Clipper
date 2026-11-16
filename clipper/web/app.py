"""FastAPI application factory for Clipper Web App."""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from clipper.approval import ApprovalQueue
from clipper.config import AppConfig
from clipper.db import Database
from clipper.web.auth import auth_middleware, is_auth_required
from clipper.web.db_web import WebDatabase
from clipper.web.fanout import PublishScheduler
from clipper.web.routes.accounts import router as accounts_router
from clipper.web.routes.auth import router as auth_router
from clipper.web.routes.clips import router as clips_router
from clipper.web.routes.dashboard import router as dashboard_router
from clipper.web.routes.logs import install_sse_log_handler, register_secret, router as logs_router
from clipper.web.routes.publishing import router as publishing_router
from clipper.web.routes.settings import router as settings_router
from clipper.web.routes.sources import router as sources_router
from clipper.web.worker_manager import WorkerManager

logger = logging.getLogger("clipper.web.app")


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection for state-changing API endpoints when auth is enabled."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            host = getattr(request.app.state, "bind_host", "127.0.0.1")
            # If auth is required or host is non-local, ensure valid origin / custom header
            if is_auth_required(host) and request.url.path.startswith("/api/"):
                # Check for custom header or standard origin check
                origin = request.headers.get("origin") or request.headers.get("referer")
                custom_hdr = request.headers.get("x-requested-with") or request.headers.get("x-csrf-token")
                # If neither custom header nor trusted origin present, deny
                if not custom_hdr and not origin:
                    return JSONResponse(
                        {"detail": "CSRF check failed: missing origin or X-Requested-With header"},
                        status_code=403,
                    )
        return await call_next(request)


def create_app(
    output_dir: Path = Path("./live_output"),
    db_path: Optional[Path] = None,
    bind_host: str = "127.0.0.1",
) -> FastAPI:
    """Create and configure the FastAPI application."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir = output_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    db_file = db_path or (output_dir / "pipeline_state.db")
    db_clips = Database(db_file)
    db_web = WebDatabase(db_file)

    # Initialize secrets for redaction in logs
    env_keys = [
        os.environ.get("GEMINI_API_KEY", ""),
        os.environ.get("OPENSHORTS_API_KEY", ""),
        os.environ.get("UPLOAD_POST_API_KEY", ""),
        os.environ.get("CLIPPER_SECRET_KEY", ""),
        os.environ.get("CLIPPER_PASSWORD", ""),
    ]
    for k in env_keys:
        if k:
            register_secret(k)

    install_sse_log_handler()

    config = AppConfig.load(
        output_dir=output_dir,
        auto_approve=False,
    )
    approval = ApprovalQueue(config=config, db=db_clips)
    worker_manager = WorkerManager(output_base=output_dir)

    settings = db_web.get_all_settings()
    openshorts_url = settings.get("openshorts_url", "http://localhost:8000")
    scheduler = PublishScheduler(
        db_web=db_web,
        db_clips=db_clips,
        openshorts_url=openshorts_url,
    )
    scheduler.start()

    app = FastAPI(
        title="Clipper Web App",
        description="Local-first AI clipper dashboard with multi-account social publishing",
        version="0.2.0",
    )

    # App state
    app.state.db_clips = db_clips
    app.state.db_web = db_web
    app.state.approval = approval
    app.state.worker_manager = worker_manager
    app.state.scheduler = scheduler
    app.state.output_dir = output_dir
    app.state.bind_host = bind_host

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth and CSRF middlewares
    app.middleware("http")(auth_middleware)
    app.add_middleware(CSRFProtectionMiddleware)

    # Register routers
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(sources_router)
    app.include_router(accounts_router)
    app.include_router(clips_router)
    app.include_router(publishing_router)
    app.include_router(settings_router)
    app.include_router(logs_router)

    # Mount static files for built React app if exists
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_candidate = static_dir / full_path
            if file_candidate.is_file():
                return FileResponse(file_candidate)
            return FileResponse(static_dir / "index.html")
    else:
        # Fallback index if frontend hasn't been built yet
        @app.get("/")
        async def fallback_root():
            return {
                "name": "Clipper Web API",
                "version": "0.2.0",
                "docs": "/docs",
                "message": "Frontend static files not yet compiled. Use Vite dev server or build frontend.",
            }

    @app.on_event("shutdown")
    def on_shutdown():
        logger.info("Shutting down Clipper web app...")
        worker_manager.stop_all()
        scheduler.stop()

    return app
