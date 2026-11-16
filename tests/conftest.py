"""Pytest fixtures and mock configurations for Live Stream Clipper tests."""

import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest
import pytest_httpx
from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient


@pytest.fixture
def tmp_path_dir() -> Generator[Path, None, None]:
    """Yield a temporary Path directory that cleans up properly."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def test_config(tmp_path_dir: Path) -> AppConfig:
    """Fixture providing an AppConfig pointing to a temporary output directory."""
    return AppConfig(
        stream_urls=["https://twitch.tv/test_stream"],
        i_own_or_have_permission=True,
        chunk_seconds=10,
        overlap_seconds=2,
        max_workers=2,
        max_disk_gb=0.001,  # ~1MB limit for quick testing of disk guards
        openshorts_url="http://testserver:8000",
        openshorts_api_key="osk_test_key",
        job_timeout_seconds=5,
        poll_initial_seconds=0.1,
        poll_max_seconds=0.5,
        output_dir=tmp_path_dir / "output",
        cleanup_chunks=False,
        auto_approve=False,
        dry_run=False,
        platforms=["upload_post"],
        daily_post_limit={"upload_post": 5, "youtube": 5, "tiktok": 5, "instagram": 5},
        min_post_gap_seconds=1,
        upload_post_api_key="test_upload_post_key",
        quality="best",
        ffprobe_check=True,
    )


@pytest.fixture
def test_db(tmp_path_dir: Path) -> Database:
    """Fixture providing a clean Database instance."""
    db_file = tmp_path_dir / "test_pipeline.db"
    return Database(db_file)


@pytest.fixture
def sample_video_file(tmp_path_dir: Path) -> Path:
    """Fixture providing a mock MP4 file."""
    video_file = tmp_path_dir / "sample.mp4"
    video_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"A" * 1024)
    return video_file
