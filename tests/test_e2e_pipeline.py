"""End-to-End integration test and dry run against a fake OpenShorts server.

Proves complete pipeline lifecycle:
record -> chunk -> upload -> process -> clip in review -> approve -> post.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import pytest
from clipper.approval import ApprovalQueue
from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient
from clipper.processor import ClipProcessor
from clipper.publisher import ClipRecord
from clipper.publisher.upload_post import UploadPostPublisher
from clipper.recorder import LiveStreamChunker, _refresh_windows_path

logger = logging.getLogger("e2e_test")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


class MockOpenShortsHandler(BaseHTTPRequestHandler):
    """Fake OpenShorts HTTP server handling uploads, process, status, and social posting."""

    sample_clip_bytes = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free"

    def log_message(self, format, *args):
        # Route HTTP server logs to standard logger
        logger.info("[MockOpenShorts] " + format % args)

    def do_GET(self):
        if self.path in ("/", "/api", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","version":"1.0.0"}')
            return

        if self.path.startswith("/api/status/"):
            job_id = self.path.split("/")[-1]
            port = self.server.server_address[1]
            response = {
                "status": "completed",
                "progress": 100,
                "logs": [
                    "Transcribing chunk with Faster-Whisper...",
                    "Detecting hooks and viral moments with Gemini Flash...",
                    "Auto-framing to vertical 9:16 layout...",
                    "Exporting final clip..."
                ],
                "result": {
                    "clips": [
                        {
                            "title": "Epic E2E Victory Moment",
                            "start": 0.5,
                            "end": 3.0,
                            "video_url": f"/download/sample_clip.mp4",
                            "download_url": f"http://127.0.0.1:{port}/download/sample_clip.mp4",
                            "video_title_for_youtube_short": "Epic E2E Victory Moment #shorts",
                            "video_description_for_instagram": "Incredible clutch! #reels",
                            "video_description_for_tiktok": "Watch this insane play #fyp",
                        }
                    ]
                }
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
            return

        if self.path.startswith("/download/"):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(self.sample_clip_bytes)))
            self.end_headers()
            self.wfile.write(self.sample_clip_bytes)
            return

        if self.path == "/api/social/user":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"profiles": [{"username": "e2e_tester", "connected": true}]}')
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""

        if self.path == "/api/uploads":
            port = self.server.server_address[1]
            data = json.loads(body.decode("utf-8")) if body else {}
            filename = data.get("filename", "chunk.mp4")
            resp = {
                "upload_id": "up_e2e_001",
                "upload_url": f"http://127.0.0.1:{port}/api/uploads/up_e2e_001",
                "method": "PUT",
                "max_mb": 500,
                "expires_in": 3600,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if self.path == "/api/process":
            data = json.loads(body.decode("utf-8")) if body else {}
            resp = {
                "job_id": "job_e2e_001",
                "status": "queued",
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if self.path == "/api/social/post":
            data = json.loads(body.decode("utf-8")) if body else {}
            resp = {
                "request_id": "req_social_e2e_888",
                "status": "success",
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        # Handle both Content-Length and Transfer-Encoding: chunked
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        total_read = 0
        if "chunked" in transfer_encoding:
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    break
                chunk_len = int(line, 16)
                if chunk_len == 0:
                    self.rfile.readline()  # trailing CRLF
                    break
                chunk_data = self.rfile.read(chunk_len)
                total_read += len(chunk_data)
                self.rfile.readline()  # trailing CRLF
        else:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                chunk_size = 65536
                while total_read < content_len:
                    n = min(chunk_size, content_len - total_read)
                    buf = self.rfile.read(n)
                    if not buf:
                        break
                    total_read += len(buf)

        resp = {
            "upload_id": "up_e2e_001",
            "bytes": total_read,
            "duration_seconds": 6.0,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode("utf-8"))


def test_full_e2e_pipeline_lifecycle(tmp_path: Path):
    """Execute complete end-to-end flow: record -> chunk -> upload -> process -> review -> approve -> post."""
    _refresh_windows_path()
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not (ffmpeg_bin and ffprobe_bin):
        pytest.skip("FFmpeg or ffprobe binary missing from PATH")

    # 1. Start local fake OpenShorts server on an ephemeral port
    server = HTTPServer(("127.0.0.1", 0), MockOpenShortsHandler)
    server_port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    openshorts_url = f"http://127.0.0.1:{server_port}"
    logger.info("Started Fake OpenShorts server at %s", openshorts_url)

    # 2. Generate a short 10-second test stream using FFmpeg
    test_stream = tmp_path / "test_stream.mp4"
    gen_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=10:size=320x240:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-g", "30",
        str(test_stream),
    ]
    subprocess.run(gen_cmd, check=True, capture_output=True)
    assert test_stream.exists() and test_stream.stat().st_size > 0

    # Also generate a valid 2-second sample MP4 clip for the download endpoint
    sample_clip_file = tmp_path / "sample_clip.mp4"
    clip_gen_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=320x240:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(sample_clip_file),
    ]
    subprocess.run(clip_gen_cmd, check=True, capture_output=True)
    MockOpenShortsHandler.sample_clip_bytes = sample_clip_file.read_bytes()

    # 3. Configure Pipeline
    output_dir = tmp_path / "e2e_output"
    config = AppConfig(
        stream_urls=[str(test_stream)],
        chunk_seconds=5,
        overlap_seconds=1,
        openshorts_url=openshorts_url,
        i_own_or_have_permission=True,
        auto_approve=False,  # Stage into review/ first to verify review & approve lifecycle
        output_dir=output_dir,
        platforms=["upload_post"],
        daily_post_limit={"upload_post": 10},
        min_post_gap_seconds=0,
        max_offline_seconds=0,  # Single-pass for test video
        ffprobe_check=True,
        dry_run=False,
    )

    db = Database(output_dir / "pipeline_state.db")
    client = OpenShortsClient(base_url=openshorts_url)
    assert client.test_connection() is True, "Connection test to fake server failed"

    processor = ClipProcessor(config=config, db=db, client=client)
    approval = ApprovalQueue(config=config, db=db)
    publisher = UploadPostPublisher(config=config, db=db, client=client)

    logger.info("=== STEP 1: RECORD & CHUNK WITH OVERLAP ===")
    chunker = LiveStreamChunker(
        stream_url=str(test_stream),
        output_dir=output_dir,
        chunk_seconds=config.chunk_seconds,
        overlap_seconds=config.overlap_seconds,
        max_offline_seconds=0,
        ffprobe_check=True,
    )

    chunks = list(chunker.iter_completed_chunks())
    logger.info("Recorded %d chunks with overlap:", len(chunks))
    for c in chunks:
        logger.info("  Chunk: %s (size: %d bytes)", c.name, c.stat().st_size)
    assert len(chunks) >= 1, "At least 1 chunk should be generated"

    first_chunk = chunks[0]

    logger.info("=== STEP 2: UPLOAD & PROCESS VIA OPENSHORTS ===")
    # Enqueue chunk and process synchronously
    processor.process_chunk(first_chunk)

    # Verify chunk was recorded in database
    chunk_row = db.get_chunk(first_chunk.stem)
    assert chunk_row is not None
    assert chunk_row["status"] == "completed"

    # Verify job was recorded in database
    jobs = db.get_processable_chunks()
    job_row = db.get_job("job_e2e_001")
    assert job_row is not None
    assert job_row["status"] == "completed"
    logger.info("Job successfully completed: %s", job_row["id"])

    logger.info("=== STEP 3: CLIP STAGED IN REVIEW ===")
    pending_clips = db.get_pending_clips()
    assert len(pending_clips) == 1, f"Expected 1 clip pending review, got {len(pending_clips)}"
    staged_clip = pending_clips[0]
    clip_id = staged_clip["id"]
    clip_path = Path(staged_clip["path"])
    logger.info("Clip awaiting review in review/: %s (id: %s)", clip_path.name, clip_id)
    assert clip_path.exists(), f"Staged clip file missing at {clip_path}"
    assert "review" in str(clip_path)

    logger.info("=== STEP 4: APPROVE CLIP VIA APPROVAL DASHBOARD ===")
    approved_title = "Epic E2E Victory Moment (Approved)"
    approval.approve_clip(clip_id=clip_id, new_title=approved_title)

    # Verify clip moved from review/ to shorts/
    approved_clip_row = None
    state = db.resume_state()
    for c in state["approved_clips"]:
        if c["id"] == clip_id:
            approved_clip_row = c
            break
    assert approved_clip_row is not None
    assert approved_clip_row["approved"] == 1
    new_path = Path(approved_clip_row["path"])
    logger.info("Clip approved and moved to shorts/: %s", new_path.name)
    assert new_path.exists(), f"Approved clip missing at {new_path}"
    assert "shorts" in str(new_path)

    logger.info("=== STEP 5: SOCIAL POST PUBLICATION ===")
    clip_record = ClipRecord(
        id=approved_clip_row["id"],
        job_id=approved_clip_row["job_id"],
        title=approved_clip_row["title"],
        path=new_path,
        approved=approved_clip_row["approved"],
        posted_platforms=approved_clip_row.get("posted_platforms", []),
    )
    req_id = publisher.post(clip_record)
    logger.info("Clip published successfully! Request ID: %s", req_id)
    assert req_id == "req_social_e2e_888"

    # Verify post record in database
    assert db.is_already_posted(hashlib_content_hash(new_path), "upload_post") is True
    logger.info("Idempotency verified: clip is recorded as posted in SQLite state DB.")

    # Clean up
    server.shutdown()
    client.close()
    logger.info("=== E2E PIPELINE RUN SUCCESSFUL: RECORD -> CHUNK -> UPLOAD -> PROCESS -> REVIEW -> APPROVE -> POST ===")


def hashlib_content_hash(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_full_e2e_pipeline_lifecycle(Path(td))
