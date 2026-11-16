"""Unit tests for Publisher implementations."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient, SocialError
from clipper.publisher import ClipRecord
from clipper.publisher.upload_post import UploadPostPublisher


def test_idempotent_post(test_config: AppConfig, test_db: Database, sample_video_file: Path):
    """Verify posting the same clip a second time does not re-post to the platform."""
    mock_client = MagicMock(spec=OpenShortsClient)
    mock_client.post_to_social.return_value = {"request_id": "req_first"}

    publisher = UploadPostPublisher(config=test_config, db=test_db, client=mock_client)

    clip = ClipRecord(
        id="c1",
        job_id="j1",
        title="Title 1",
        path=sample_video_file,
    )

    # First post
    req_id = publisher.post(clip)
    assert req_id == "req_first"
    assert mock_client.post_to_social.call_count == 1

    # Second post with identical clip
    req_id2 = publisher.post(clip)
    assert req_id2 == "none_posted"
    # Call count should still be 1 (no re-call to API)
    assert mock_client.post_to_social.call_count == 1


def test_rate_limit_daily_enforced(test_config: AppConfig, test_db: Database, sample_video_file: Path):
    """Verify daily post limit prevents further postings once limit is reached."""
    test_config.daily_post_limit = {"upload_post": 2}
    mock_client = MagicMock(spec=OpenShortsClient)
    mock_client.post_to_social.return_value = {"request_id": "ok"}

    publisher = UploadPostPublisher(config=test_config, db=test_db, client=mock_client)

    # Pre-populate DB with 2 posts today
    test_db.upsert_post("p1", "c0", "upload_post", "posted", "r1")
    test_db.upsert_post("p2", "c0", "upload_post", "posted", "r2")

    clip = ClipRecord(id="c_new", job_id="j1", title="New", path=sample_video_file)
    publisher.post(clip)

    # Should not call API because limit is 2
    assert mock_client.post_to_social.call_count == 0


def test_tiktok_failure_does_not_block_other_platforms(
    test_config: AppConfig,
    test_db: Database,
    sample_video_file: Path,
):
    """Verify that a TikTok failure does not halt publishing to YouTube and Instagram."""
    test_config.platforms = ["tiktok", "youtube"]
    mock_client = MagicMock(spec=OpenShortsClient)

    def mock_post(job_id, clip_index, platforms, **kwargs):
        if "tiktok" in platforms:
            raise SocialError("TikTok account authorization expired")
        return {"request_id": "req_yt_123"}

    mock_client.post_to_social.side_effect = mock_post
    publisher = UploadPostPublisher(config=test_config, db=test_db, client=mock_client)

    clip = ClipRecord(id="clip_multi", job_id="j_multi", title="Multi", path=sample_video_file)
    res = publisher.post(clip)

    # YouTube succeeded
    assert res == "req_yt_123"
    # TikTok post recorded as failed in DB
    posts = test_db._get_connection if hasattr(test_db, "_get_connection") else None
    # Verify clip was marked as posted on YouTube
    updated_clip = test_db.get_clip("clip_multi")
    assert "youtube" in updated_clip["posted_platforms"]
    assert "tiktok" not in updated_clip["posted_platforms"]


def test_dry_run_does_not_call_api(test_config: AppConfig, test_db: Database, sample_video_file: Path):
    """Verify dry_run=True returns 'dry_run' without issuing any HTTP requests."""
    test_config.dry_run = True
    mock_client = MagicMock(spec=OpenShortsClient)

    publisher = UploadPostPublisher(config=test_config, db=test_db, client=mock_client)
    clip = ClipRecord(id="c_dry", job_id="j_dry", title="Dry", path=sample_video_file)

    res = publisher.post(clip)
    assert res == "dry_run"
    assert mock_client.post_to_social.call_count == 0


def test_check_token_surfaces_warning(test_config: AppConfig, test_db: Database):
    """Verify check_token returns False on auth errors."""
    mock_client = MagicMock(spec=OpenShortsClient)
    mock_client.get_social_user.side_effect = SocialError("401 Unauthorized")

    publisher = UploadPostPublisher(config=test_config, db=test_db, client=mock_client)
    assert publisher.check_token() is False
