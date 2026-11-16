"""Unit tests for ClipProcessor."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient
from clipper.processor import ClipProcessor, sanitize_filename


def test_sanitize_filename():
    """Verify filename sanitization removes special characters and reserved names."""
    name = sanitize_filename("What an EPIC play!?? *cool*", "chunk_0001", 1)
    assert "What_an_EPIC_play_cool" in name
    assert name.endswith(".mp4")

    # Windows reserved name
    reserved = sanitize_filename("CON", "chunk_0002", 2)
    assert "clip_2" in reserved


def test_clip_deduplication(test_config: AppConfig, test_db: Database):
    """Verify deduplication skips clips overlapping >50%."""
    mock_client = MagicMock(spec=OpenShortsClient)
    processor = ClipProcessor(config=test_config, db=test_db, client=mock_client)

    # Record first clip: 10s to 40s (duration 30s)
    processor.record_clip_window(10.0, 40.0, "Clip 1")

    # Second clip: 15s to 35s (fully inside 10..40, intersection 20s, duration 20s -> 100% overlap)
    assert processor.is_overlapping_clip(15.0, 35.0, "Clip 2") is True

    # Third clip: 25s to 50s (intersection with 10..40 is 15s, duration 25s -> 15/25 = 60% > 50%)
    assert processor.is_overlapping_clip(25.0, 50.0, "Clip 3") is True

    # Fourth clip: 36s to 60s (intersection with 10..40 is 4s, duration 24s -> 4/24 = 16% < 50%)
    assert processor.is_overlapping_clip(36.0, 60.0, "Clip 4") is False


def test_disk_cleanup_triggers_at_limit(tmp_path_dir: Path, test_db: Database):
    """Verify oldest completed chunks are pruned when directory size exceeds max_disk_gb."""
    cfg = AppConfig(
        output_dir=tmp_path_dir / "out",
        max_disk_gb=0.00001,  # ~10 KB limit
        stream_urls=["https://twitch.tv/test"],
    )
    chunks_dir = cfg.output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Create two chunks
    chunk1 = chunks_dir / "chunk_0001.mp4"
    chunk2 = chunks_dir / "chunk_0002.mp4"
    chunk1.write_bytes(b"A" * 20000)
    chunk2.write_bytes(b"B" * 20000)

    # Register in DB: chunk1 completed earlier, chunk2 completed later
    test_db.upsert_chunk("chunk_0001", str(chunk1), "completed", created_at=time.time() - 100)
    test_db.upsert_chunk("chunk_0002", str(chunk2), "completed", created_at=time.time() - 10)

    mock_client = MagicMock(spec=OpenShortsClient)
    processor = ClipProcessor(config=cfg, db=test_db, client=mock_client)

    processor.check_and_enforce_disk_limit()

    # chunk1 (older) should have been pruned to bring size down
    assert not chunk1.exists()


def test_enqueue_chunk_skips_already_completed(test_config: AppConfig, test_db: Database, tmp_path_dir: Path):
    """Verify that chunks marked as 'completed' in DB are not re-enqueued."""
    chunk_path = tmp_path_dir / "chunk_done.mp4"
    chunk_path.write_bytes(b"done")

    test_db.upsert_chunk("chunk_done", str(chunk_path), "completed")

    mock_client = MagicMock(spec=OpenShortsClient)
    processor = ClipProcessor(config=test_config, db=test_db, client=mock_client)

    processor.enqueue_chunk(chunk_path)
    assert processor.work_queue.qsize() == 0


def test_worker_pool_concurrent_execution(test_config: AppConfig, test_db: Database, tmp_path_dir: Path):
    """Verify worker pool processes multiple chunks concurrently."""
    test_config.max_workers = 2
    mock_client = MagicMock(spec=OpenShortsClient)

    # Mock upload slot, stream upload, process, poll
    mock_client.create_upload_slot.return_value = {"upload_id": "u1", "upload_url": "http://test/u1"}
    mock_client.trigger_process.return_value = "j1"
    mock_client.poll_status.return_value = {"status": "completed", "result": {"clips": []}}

    processor = ClipProcessor(config=test_config, db=test_db, client=mock_client)

    chunk_a = tmp_path_dir / "chunk_a.mp4"
    chunk_b = tmp_path_dir / "chunk_b.mp4"
    chunk_a.write_bytes(b"data_a")
    chunk_b.write_bytes(b"data_b")

    processor.start_workers()
    processor.enqueue_chunk(chunk_a)
    processor.enqueue_chunk(chunk_b)

    # Wait for queue to be processed
    processor.work_queue.join()
    processor.stop()

    assert test_db.get_chunk("chunk_a")["status"] == "completed"
    assert test_db.get_chunk("chunk_b")["status"] == "completed"
