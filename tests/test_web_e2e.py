"""End-to-end integration test with real FFmpeg lavfi test stream through Web API.

Validates the full flow against a fake OpenShorts server:
record -> chunk -> upload -> process -> clip in review -> approve -> post to two mock accounts.

Skips gracefully if ffmpeg is not available on PATH.
"""

import http.server
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient
from clipper.processor import ClipProcessor
from clipper.recorder import LiveStreamChunker
from clipper.web.app import create_app
from clipper.web.crypto import encrypt_key
from clipper.web.fanout import fan_out_post

logger = logging.getLogger("test.e2e_web")


class MockOpenShortsHandler(http.server.BaseHTTPRequestHandler):
    """Mock OpenShorts HTTP server handling chunked streaming uploads and processing."""

    def log_message(self, format, *args):
        pass  # Quiet

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ready"}')
        elif self.path.startswith("/api/status/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            res = {
                "status": "completed",
                "logs": ["Audio transcribed", "YOLO detected faces", "Gemini viral moments picked"],
                "result": {
                    "clips": [
                        {
                            "title": "E2E Viral Moment",
                            "download_url": "/videos/test_clip.mp4",
                            "start": 1.0,
                            "end": 8.0,
                            "virality_score": 9.4,
                        }
                    ],
                    "cost_analysis": {"total_cost": 0.005},
                },
            }
            self.wfile.write(json.dumps(res).encode())
        elif self.path == "/videos/test_clip.mp4":
            # Serve small video bytes
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            dummy_mp4 = getattr(self.server, "sample_clip_bytes", b"mock mp4 stream bytes 12345")
            self.send_header("Content-Length", str(len(dummy_mp4)))
            self.end_headers()
            self.wfile.write(dummy_mp4)
        elif self.path == "/api/social/user":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"profiles": [{"username": "e2e_user", "connected": ["youtube", "instagram"]}]}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/uploads":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "upload_id": "e2e_upl_1",
                "upload_url": "/api/uploads/e2e_upl_1",
                "method": "PUT",
                "max_mb": 500,
                "expires_in": 3600,
            }).encode())
        elif self.path == "/api/process":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"job_id": "e2e_job_001"}')
        elif self.path == "/api/social/post":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"request_id": "social_req_999", "status": "posted"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path.startswith("/api/uploads/"):
            # Consume chunked or raw body
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                self.rfile.read(length)
            else:
                while True:
                    line = self.rfile.readline()
                    if not line:
                        break
                    chunk_len = int(line.strip(), 16)
                    if chunk_len == 0:
                        self.rfile.read(2)  # trailing CRLF
                        break
                    self.rfile.read(chunk_len + 2)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "uploaded", "upload_id": "e2e_upl_1"}')
        else:
            self.send_response(404)
            self.end_headers()


def test_web_e2e_real_ffmpeg_fake_server():
    """Real FFmpeg lavfi generation -> chunking -> upload -> review -> approve -> post to 2 accounts."""
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed or not available on PATH")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dir = Path(tmpdir)
        source_video = tmp_dir / "test_stream.mp4"
        output_dir = tmp_dir / "live_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        db_path = output_dir / "pipeline_state.db"

        # 1. Generate 12-second test video using real FFmpeg lavfi
        logger.info("Generating lavfi test source video...")
        cmd_gen = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=12:size=640x360:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(source_video),
        ]
        ret = subprocess.run(cmd_gen, capture_output=True, timeout=30)
        assert ret.returncode == 0, f"FFmpeg generation failed: {ret.stderr.decode()}"
        assert source_video.exists() and source_video.stat().st_size > 1000

        # 2. Start mock OpenShorts server
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockOpenShortsHandler)
        server.sample_clip_bytes = source_video.read_bytes()
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        mock_server_url = f"http://127.0.0.1:{server_port}"
        logger.info("Mock OpenShorts running on %s", mock_server_url)

        try:
            # 3. Create FastAPI app & test client
            app = create_app(output_dir=output_dir, db_path=db_path, bind_host="127.0.0.1")
            client = TestClient(app)
            db_web = app.state.db_web
            db_clips = app.state.db_clips

            # 4. Set OpenShorts server URL in settings
            db_web.set_setting("openshorts_url", mock_server_url)

            # 5. Create two social accounts (YouTube and Instagram)
            acc1_id = db_web.create_account(
                label="Account 1 (YouTube)",
                upload_post_api_key_enc=encrypt_key("fake_key_1"),
                profile_name="yt_profile",
                platforms_enabled=["youtube"],
            )
            acc2_id = db_web.create_account(
                label="Account 2 (Instagram)",
                upload_post_api_key_enc=encrypt_key("fake_key_2"),
                profile_name="ig_profile",
                platforms_enabled=["instagram"],
            )

            # 6. Add source video through Web API with ownership affirmed
            res = client.post("/api/sources", json={
                "url": str(source_video.resolve()),
                "label": "E2E Test Stream",
                "chunk_seconds": 6,
                "overlap_seconds": 2,
                "i_own_or_have_permission": True,
                "target_account_ids": [acc1_id, acc2_id],
            })
            assert res.status_code == 201
            source_id = res.json()["id"]

            # 7. Step 1: Record -> Chunk with real FFmpeg
            chunker = LiveStreamChunker(
                stream_url=str(source_video.resolve()),
                output_dir=output_dir,
                chunk_seconds=6,
                overlap_seconds=2,
                max_offline_seconds=1,
            )
            chunks = []
            for c in chunker.iter_completed_chunks():
                chunks.append(c)
                chunker.stop()
                break
            assert len(chunks) >= 1, "At least one chunk must be generated by real FFmpeg"
            first_chunk = chunks[0]
            assert first_chunk.exists()
            logger.info("Generated real chunk: %s (size=%d)", first_chunk.name, first_chunk.stat().st_size)

            # 8. Step 2 & 3: Upload -> Process with OpenShorts Client
            os_client = OpenShortsClient(base_url=mock_server_url)
            config = AppConfig.load(
                output_dir=output_dir,
                chunk_seconds=6,
                overlap_seconds=2,
                openshorts_url=mock_server_url,
                auto_approve=False,
            )
            processor = ClipProcessor(config=config, db=db_clips, client=os_client)
            processor.process_chunk(first_chunk)

            # 9. Step 4: Verify clip is staged in review/
            pending = client.get("/api/clips?status=pending").json()
            assert len(pending) >= 1, "Clip must be in review queue"
            clip_to_approve = pending[0]
            clip_id = clip_to_approve["id"]
            logger.info("Clip awaiting review: %s (%s)", clip_to_approve["title"], clip_id)

            # 10. Step 5: Approve via Web API
            res = client.post(f"/api/clips/{clip_id}/approve", json={"new_title": "Approved Viral Clip"})
            assert res.status_code == 200
            approved_data = res.json()
            assert approved_data["approved"] == 1
            assert (output_dir / "shorts" / Path(approved_data["path"]).name).exists()
            logger.info("Clip approved and moved to shorts: %s", approved_data["path"])

            # 11. Step 6: Post to both mock accounts via Web API
            post_res = client.post("/api/posts/post", json={
                "clip_id": clip_id,
                "account_ids": [acc1_id, acc2_id],
                "platforms": ["youtube", "instagram"],
                "dry_run": False,
            })
            assert post_res.status_code == 200

            # 12. Verify all posts in posts_v2 table (2 accounts x 2 platforms = 4 posts)
            posts = db_web.list_posts_v2(clip_id=clip_id)
            assert len(posts) == 4, f"Expected 4 post records, found {len(posts)}"
            for p in posts:
                assert p["status"] == "posted"
                assert p["request_id"] == "social_req_999"
                logger.info("Verified post: account=%s platform=%s status=%s",
                            p["account_id"], p["platform"], p["status"])

            logger.info("E2E Test Succeeded: record -> chunk -> upload -> process -> review -> approve -> post to 2 accounts!")

        finally:
            server.shutdown()
            server.server_close()
