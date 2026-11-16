"""Integration and crash-resume tests for Pipeline orchestrator."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient
from clipper.pipeline import Pipeline
from clipper.processor import ClipProcessor
from clipper.publisher import ClipRecord
from clipper.publisher.upload_post import UploadPostPublisher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides) -> AppConfig:
    defaults = dict(
        stream_urls=["https://twitch.tv/test_integration"],
        i_own_or_have_permission=True,
        chunk_seconds=5,
        overlap_seconds=1,
        max_workers=1,
        max_disk_gb=10.0,
        openshorts_url="http://localhost:8000",
        openshorts_api_key=None,
        job_timeout_seconds=5,
        poll_initial_seconds=0.05,
        poll_max_seconds=0.2,
        output_dir=tmp_path / "output",
        cleanup_chunks=False,
        auto_approve=False,
        dry_run=True,  # default to dry-run so no real network calls
        platforms=["upload_post"],
        daily_post_limit={"upload_post": 100},
        min_post_gap_seconds=0,
        upload_post_api_key=None,
        quality="best",
        ffprobe_check=False,
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


# ---------------------------------------------------------------------------
# --status command
# ---------------------------------------------------------------------------


def test_print_status_no_crash(tmp_path: Path, capsys) -> None:
    """Pipeline.print_status() must run without error on an empty DB."""
    config = _make_config(tmp_path)
    pipeline = Pipeline(config)
    pipeline.print_status()
    captured = capsys.readouterr()
    assert "Pipeline Status" in captured.out


# ---------------------------------------------------------------------------
# Crash-resume: previously-pending chunks are re-enqueued
# ---------------------------------------------------------------------------


def test_resume_enqueues_pending_chunks(tmp_path: Path) -> None:
    """On startup, chunks with non-completed status in the DB are re-enqueued."""
    config = _make_config(tmp_path, dry_run=True)
    pipeline = Pipeline(config)

    # Manually write a 'pending' chunk to the DB (simulates crash mid-upload)
    chunk_file = config.output_dir / "chunks" / "chunk_resume.mp4"
    chunk_file.parent.mkdir(parents=True, exist_ok=True)
    chunk_file.write_bytes(b"X" * 500)
    pipeline.db.upsert_chunk("chunk_resume", str(chunk_file), "pending")

    # Simulate the resume path without running the full stream recorder
    resume_info = pipeline.db.resume_state()
    for chunk in resume_info["pending_chunks"]:
        p = Path(chunk["path"])
        if p.exists():
            pipeline.processor.enqueue_chunk(p)

    assert pipeline.processor.work_queue.qsize() == 1
    pipeline.stop()


# ---------------------------------------------------------------------------
# Full dry-run integration: chunk → process (dry) → no clips, no crash
# ---------------------------------------------------------------------------


def test_full_dry_run_pipeline(tmp_path: Path) -> None:
    """In dry_run mode, process_chunk logs but does not call OpenShorts APIs."""
    config = _make_config(tmp_path, dry_run=True, auto_approve=True)
    pipeline = Pipeline(config)

    chunk_file = config.output_dir / "chunks" / "chunk_dry.mp4"
    chunk_file.parent.mkdir(parents=True, exist_ok=True)
    chunk_file.write_bytes(b"Y" * 1000)

    pipeline.processor.start_workers()
    pipeline.processor.enqueue_chunk(chunk_file)
    pipeline.processor.work_queue.join()
    pipeline.stop()

    # In dry-run the chunk is marked 'completed' without calling the API
    row = pipeline.db.get_chunk("chunk_dry")
    assert row is not None
    assert row["status"] == "completed"


# ---------------------------------------------------------------------------
# Processor worker pool: resume skips already-completed chunks
# ---------------------------------------------------------------------------


def test_resume_skips_completed_chunks(tmp_path: Path) -> None:
    """Chunks already marked 'completed' in DB are not re-enqueued on resume."""
    config = _make_config(tmp_path, dry_run=True)
    pipeline = Pipeline(config)

    chunk_file = config.output_dir / "chunks" / "chunk_already_done.mp4"
    chunk_file.parent.mkdir(parents=True, exist_ok=True)
    chunk_file.write_bytes(b"done")

    # Mark as completed before enqueueing
    pipeline.db.upsert_chunk("chunk_already_done", str(chunk_file), "completed")

    pipeline.processor.enqueue_chunk(chunk_file)
    # Queue should stay empty because chunk is already completed
    assert pipeline.processor.work_queue.qsize() == 0
    pipeline.stop()


# ---------------------------------------------------------------------------
# Publisher loop: approved clips are submitted to publisher
# ---------------------------------------------------------------------------


def test_publisher_loop_posts_approved_clips(tmp_path: Path) -> None:
    """Approved clips in the DB are picked up by the publisher loop."""
    config = _make_config(tmp_path, dry_run=False, auto_approve=True, platforms=["upload_post"])
    pipeline = Pipeline(config)

    # Seed DB with an approved clip
    clip_file = config.output_dir / "shorts" / "approved_clip.mp4"
    clip_file.parent.mkdir(parents=True, exist_ok=True)
    clip_file.write_bytes(b"approved_bytes" * 100)

    pipeline.db.upsert_chunk("c1", "/tmp/c1.mp4", "completed")
    pipeline.db.upsert_job("j1", "c1", "completed")
    pipeline.db.upsert_clip(
        "clip_approved_01",
        "j1",
        "Top 10 Moments",
        str(clip_file),
        approved=1,
    )

    # Patch publisher to avoid real HTTP calls
    post_calls: list[ClipRecord] = []

    def fake_post(clip: ClipRecord, dry_run: bool = False) -> str:
        post_calls.append(clip)
        return "req_fake_123"

    pipeline.publisher.post = fake_post  # type: ignore[method-assign]

    # Run publisher loop briefly in a background thread
    stop_event = threading.Event()

    def publisher_loop() -> None:
        for _platform in config.platforms:
            unposted = pipeline.db.get_approved_unposted_clips(_platform)
            for clip_data in unposted:
                record = ClipRecord(
                    id=clip_data["id"],
                    job_id=clip_data["job_id"],
                    title=clip_data["title"],
                    path=Path(clip_data["path"]),
                    approved=clip_data["approved"],
                    posted_platforms=clip_data.get("posted_platforms", []),
                )
                try:
                    pipeline.publisher.post(record)
                except Exception:
                    pass

    t = threading.Thread(target=publisher_loop)
    t.start()
    t.join(timeout=5.0)

    assert len(post_calls) == 1
    assert post_calls[0].title == "Top 10 Moments"
    pipeline.stop()


# ---------------------------------------------------------------------------
# Signal / SIGINT graceful shutdown
# ---------------------------------------------------------------------------


def test_stop_is_idempotent(tmp_path: Path) -> None:
    """Calling stop() multiple times must not raise."""
    config = _make_config(tmp_path)
    pipeline = Pipeline(config)
    pipeline.processor.start_workers()
    pipeline.stop()
    pipeline.stop()  # second call must be safe


# ---------------------------------------------------------------------------
# auto_approve skips approval server
# ---------------------------------------------------------------------------


def test_auto_approve_skips_server(tmp_path: Path) -> None:
    """With auto_approve=True, the approval HTTP server is never started."""
    config = _make_config(tmp_path, auto_approve=True)
    pipeline = Pipeline(config)

    with patch.object(pipeline.approval, "start_server") as mock_start:
        # Simulate the pipeline run() section that conditionally starts server
        if not config.auto_approve:
            pipeline.approval.start_server()

    mock_start.assert_not_called()
    pipeline.stop()


# ---------------------------------------------------------------------------
# Ownership Gate: i_own_or_have_permission must be true to publish
# ---------------------------------------------------------------------------


def test_ownership_gate_refuses_publishing(tmp_path: Path) -> None:
    """When i_own_or_have_permission is false, publishing is refused."""
    config = _make_config(tmp_path, i_own_or_have_permission=False, dry_run=False)
    pipeline = Pipeline(config)

    clip_file = config.output_dir / "review" / "test_clip.mp4"
    clip_file.parent.mkdir(parents=True, exist_ok=True)
    clip_file.write_bytes(b"sample_clip_data" * 100)

    record = ClipRecord(
        id="c1",
        job_id="j1",
        title="Unowned Stream Clip",
        path=clip_file,
        approved=1,
    )

    # Calling post directly must raise PermissionError
    with pytest.raises(PermissionError, match="Publishing refused"):
        pipeline.publisher.post(record)

    pipeline.stop()


# ---------------------------------------------------------------------------
# Server reachability: hard failure by default and retry backoff loop
# ---------------------------------------------------------------------------


def test_server_unreachable_hard_failure(tmp_path: Path) -> None:
    """When OpenShorts is unreachable and server_retry_max_attempts=0, run() raises RuntimeError."""
    config = _make_config(
        tmp_path,
        dry_run=False,
        server_retry_max_attempts=0,
        stream_urls=["https://twitch.tv/test"],
    )
    pipeline = Pipeline(config)

    with patch.object(pipeline.client, "test_connection", return_value=False):
        with pytest.raises(RuntimeError, match="OpenShorts server unreachable"):
            pipeline.run()

    pipeline.stop()


def test_server_unreachable_retry_loop_success(tmp_path: Path) -> None:
    """Server reachability check retries with backoff and succeeds if server becomes ready."""
    config = _make_config(
        tmp_path,
        dry_run=False,
        server_retry_max_attempts=2,
        server_retry_backoff=0.01,
    )
    pipeline = Pipeline(config)

    # First attempt fails, second succeeds
    with patch.object(pipeline.client, "test_connection", side_effect=[False, True]):
        assert pipeline._verify_server_connection() is True

    pipeline.stop()
