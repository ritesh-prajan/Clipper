"""Approval queue and lightweight HTTP review server for manual clip inspection."""

import html
import http.server
import logging
import os
import shutil
import threading
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

from clipper.config import AppConfig
from clipper.db import Database

logger = logging.getLogger("clipper.approval")


class ApprovalQueue:
    """Manages clip staging, manual review, HTML dashboard generation, and approval HTTP server."""

    def __init__(self, config: AppConfig, db: Database, host: str = "127.0.0.1", port: int = 8765):
        """Initialize the approval queue.

        Args:
            config: Application configuration.
            db: Database instance.
            host: HTTP server bind address.
            port: HTTP server listening port (default: 8765).
        """
        self.config = config
        self.db = db
        self.host = host
        self.port = port

        self.review_dir = self.config.output_dir / "review"
        self.shorts_dir = self.config.output_dir / "shorts"
        self.rejected_dir = self.config.output_dir / "rejected"

        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.shorts_dir.mkdir(parents=True, exist_ok=True)
        self.rejected_dir.mkdir(parents=True, exist_ok=True)

        self.index_html_path = self.review_dir / "index.html"
        self._server: Optional[http.server.HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start_server(self) -> None:
        """Start the background HTTP approval server."""
        if self.config.auto_approve:
            logger.info("auto_approve is enabled. Skipping review HTTP server.")
            return

        with self._lock:
            if self._server is not None:
                return

            queue_ref = self

            class ApprovalHandler(http.server.BaseHTTPRequestHandler):
                """Handles web UI requests and form submissions."""

                def log_message(self, format: str, *args) -> None:
                    # Suppress noisy HTTP request logging
                    pass

                def do_GET(self) -> None:
                    parsed = urllib.parse.urlparse(self.path)
                    if parsed.path in ("/", "/index.html"):
                        queue_ref.generate_html()
                        if queue_ref.index_html_path.exists():
                            content = queue_ref.index_html_path.read_bytes()
                            self.send_response(200)
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                            self.send_header("Content-Length", str(len(content)))
                            self.end_headers()
                            self.wfile.write(content)
                        else:
                            self.send_error(404, "Dashboard HTML not found")
                    elif parsed.path.startswith("/video/"):
                        clip_id = parsed.path.split("/video/")[-1]
                        clip = queue_ref.db.get_clip(clip_id)
                        if clip and Path(clip["path"]).exists():
                            file_path = Path(clip["path"])
                            self.send_response(200)
                            self.send_header("Content-Type", "video/mp4")
                            self.send_header("Content-Length", str(file_path.stat().st_size))
                            self.end_headers()
                            with open(file_path, "rb") as f:
                                shutil.copyfileobj(f, self.wfile)
                        else:
                            self.send_error(404, "Video clip not found")
                    else:
                        self.send_error(404, "Not found")

                def do_POST(self) -> None:
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    params = urllib.parse.parse_qs(body)

                    clip_id = params.get("clip_id", [""])[0]
                    new_title = params.get("new_title", [""])[0].strip() or None

                    if self.path == "/approve" and clip_id:
                        queue_ref.approve_clip(clip_id, new_title)
                    elif self.path == "/reject" and clip_id:
                        queue_ref.reject_clip(clip_id)
                    elif self.path == "/edit" and clip_id and new_title:
                        queue_ref.edit_caption(clip_id, new_title)

                    # Redirect back to home
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()

            try:
                self._server = http.server.ThreadingHTTPServer((self.host, self.port), ApprovalHandler)
                self._server_thread = threading.Thread(
                    target=self._server.serve_forever,
                    name="ApprovalServer",
                    daemon=True,
                )
                self._server_thread.start()
                logger.info("Approval web dashboard active at http://%s:%s", self.host, self.port)
            except Exception as e:
                logger.error("Failed to start approval server on %s:%s: %s", self.host, self.port, e)

    def stop_server(self) -> None:
        """Stop the review HTTP server."""
        with self._lock:
            if self._server:
                logger.info("Shutting down approval web server...")
                self._server.shutdown()
                self._server.server_close()
                self._server = None
                self._server_thread = None

    def approve_clip(self, clip_id: str, new_title: Optional[str] = None) -> bool:
        """Approve a clip, moving it from review/ to shorts/ and marking approved=1."""
        clip = self.db.get_clip(clip_id)
        if not clip:
            logger.warning("Clip %s not found in DB.", clip_id)
            return False

        src_path = Path(clip["path"])
        dest_path = self.shorts_dir / src_path.name

        if src_path.exists():
            try:
                shutil.move(str(src_path), str(dest_path))
            except Exception as e:
                logger.error("Failed to move %s to %s: %s", src_path, dest_path, e)
                dest_path = src_path
        else:
            dest_path = self.shorts_dir / src_path.name

        final_title = new_title if new_title else clip["title"]
        self.db.upsert_clip(
            clip_id=clip_id,
            job_id=clip["job_id"],
            title=final_title,
            path=str(dest_path),
            approved=1,
            posted_platforms=clip.get("posted_platforms", []),
        )
        logger.info("Approved clip '%s' -> %s", final_title, dest_path.name)
        self.generate_html()
        return True

    def reject_clip(self, clip_id: str) -> bool:
        """Reject a clip, moving it to rejected/ and marking approved=-1."""
        clip = self.db.get_clip(clip_id)
        if not clip:
            return False

        src_path = Path(clip["path"])
        dest_path = self.rejected_dir / src_path.name

        if src_path.exists():
            try:
                shutil.move(str(src_path), str(dest_path))
            except Exception as e:
                logger.error("Failed to move %s to %s: %s", src_path, dest_path, e)
                dest_path = src_path

        self.db.mark_clip_rejected(clip_id, new_path=str(dest_path))
        logger.info("Rejected clip '%s' (moved to %s)", clip["title"], dest_path.name)
        self.generate_html()
        return True

    def edit_caption(self, clip_id: str, new_title: str) -> bool:
        """Update a pending clip's title or caption."""
        clip = self.db.get_clip(clip_id)
        if not clip:
            return False

        self.db.upsert_clip(
            clip_id=clip_id,
            job_id=clip["job_id"],
            title=new_title,
            path=clip["path"],
            approved=clip["approved"],
            posted_platforms=clip.get("posted_platforms", []),
        )
        logger.info("Updated caption for clip %s to: '%s'", clip_id, new_title)
        self.generate_html()
        return True

    def generate_html(self) -> Path:
        """Regenerate review/index.html listing all pending clips with preview and forms."""
        pending_clips = self.db.get_pending_clips()

        cards_html = []
        if not pending_clips:
            cards_html.append(
                """
                <div class="empty-state">
                    <h3>🎉 No Pending Clips</h3>
                    <p>All generated shorts have been reviewed or are currently processing.</p>
                </div>
                """
            )
        else:
            for clip in pending_clips:
                clip_id = html.escape(clip["id"])
                title = html.escape(clip["title"])
                filename = html.escape(Path(clip["path"]).name)

                card = f"""
                <div class="clip-card">
                    <div class="video-container">
                        <video controls preload="metadata" src="/video/{clip_id}"></video>
                    </div>
                    <div class="clip-details">
                        <h4>{title}</h4>
                        <p class="filename">{filename}</p>
                        
                        <form method="POST" action="/approve" class="action-form">
                            <input type="hidden" name="clip_id" value="{clip_id}">
                            <label>Caption / Title:</label>
                            <input type="text" name="new_title" value="{title}" class="caption-input">
                            <div class="button-group">
                                <button type="submit" class="btn btn-approve">Approve & Publish</button>
                                <button type="submit" formaction="/reject" class="btn btn-reject">Reject</button>
                                <button type="submit" formaction="/edit" class="btn btn-edit">Save Caption</button>
                            </div>
                        </form>
                    </div>
                </div>
                """
                cards_html.append(card)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Stream Clipper - Clip Review</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #3b82f6;
            --success: #10b981;
            --danger: #ef4444;
            --border: #334155;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 24px;
        }}
        .header {{
            max-width: 1200px;
            margin: 0 auto 24px auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
        }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .header .badge {{
            background: var(--primary);
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 14px;
            font-weight: 600;
        }}
        .grid {{
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 24px;
        }}
        .clip-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .video-container {{
            background: #000;
            width: 100%;
            aspect-ratio: 9/16;
            max-height: 480px;
            display: flex;
            justify-content: center;
        }}
        video {{
            width: 100%;
            height: 100%;
            object-fit: contain;
        }}
        .clip-details {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }}
        .clip-details h4 {{ margin: 0 0 4px 0; font-size: 16px; }}
        .filename {{ color: var(--text-muted); font-size: 12px; margin: 0 0 16px 0; word-break: break-all; }}
        .action-form {{ display: flex; flex-direction: column; gap: 8px; margin-top: auto; }}
        label {{ font-size: 12px; color: var(--text-muted); }}
        .caption-input {{
            background: #0f172a;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 14px;
        }}
        .button-group {{
            display: flex;
            gap: 8px;
            margin-top: 8px;
        }}
        .btn {{
            flex: 1;
            padding: 8px 12px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            font-size: 13px;
            transition: opacity 0.2s;
        }}
        .btn:hover {{ opacity: 0.9; }}
        .btn-approve {{ background: var(--success); color: white; }}
        .btn-reject {{ background: var(--danger); color: white; }}
        .btn-edit {{ background: var(--primary); color: white; }}
        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 64px 0;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Live Stream Clipper Review Dashboard</h1>
        <div class="badge">{len(pending_clips)} Pending Review</div>
    </div>
    <div class="grid">
        {"".join(cards_html)}
    </div>
</body>
</html>
"""
        self.index_html_path.write_text(html_content, encoding="utf-8")
        return self.index_html_path
