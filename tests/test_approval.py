"""Unit tests for ApprovalQueue and review server."""

import urllib.request
import urllib.parse
from pathlib import Path

from clipper.approval import ApprovalQueue
from clipper.config import AppConfig
from clipper.db import Database


def test_manual_approval_moves_clip(test_config: AppConfig, test_db: Database, tmp_path_dir: Path):
    """Verify manual approval transitions clip from review/ to shorts/ and marks approved=1."""
    queue = ApprovalQueue(config=test_config, db=test_db)

    # Place a clip in review_dir
    review_clip_path = queue.review_dir / "review_clip.mp4"
    review_clip_path.write_bytes(b"review_content")

    test_db.upsert_clip(
        clip_id="c_review_1",
        job_id="j1",
        title="Original Title",
        path=str(review_clip_path),
        approved=0,
    )

    # Approve with edited caption
    success = queue.approve_clip("c_review_1", new_title="Better Title")
    assert success is True

    # Verify moved to shorts_dir
    dest_path = queue.shorts_dir / "review_clip.mp4"
    assert dest_path.exists()
    assert not review_clip_path.exists()

    # Verify DB state
    clip = test_db.get_clip("c_review_1")
    assert clip["approved"] == 1
    assert clip["title"] == "Better Title"
    assert clip["path"] == str(dest_path)


def test_reject_moves_clip(test_config: AppConfig, test_db: Database):
    """Verify rejecting a clip moves it to rejected/ and marks approved=-1."""
    queue = ApprovalQueue(config=test_config, db=test_db)

    review_clip_path = queue.review_dir / "bad_clip.mp4"
    review_clip_path.write_bytes(b"bad_content")

    test_db.upsert_clip(
        clip_id="c_reject_1",
        job_id="j1",
        title="Bad Title",
        path=str(review_clip_path),
        approved=0,
    )

    success = queue.reject_clip("c_reject_1")
    assert success is True

    dest_path = queue.rejected_dir / "bad_clip.mp4"
    assert dest_path.exists()
    assert not review_clip_path.exists()

    clip = test_db.get_clip("c_reject_1")
    assert clip["approved"] == -1


def test_http_approval_server_form_submission(test_config: AppConfig, test_db: Database):
    """Verify approval server handles HTTP POST /approve request."""
    # Use a high random test port
    queue = ApprovalQueue(config=test_config, db=test_db, host="127.0.0.1", port=18765)

    clip_path = queue.review_dir / "web_clip.mp4"
    clip_path.write_bytes(b"web_content")
    test_db.upsert_clip(
        clip_id="c_web_1",
        job_id="j1",
        title="Web Title",
        path=str(clip_path),
        approved=0,
    )

    queue.start_server()

    try:
        data = urllib.parse.urlencode({"clip_id": "c_web_1", "new_title": "Web Approved"}).encode()
        req = urllib.request.Request("http://127.0.0.1:18765/approve", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200 or resp.geturl() == "http://127.0.0.1:18765/"

        clip = test_db.get_clip("c_web_1")
        assert clip["approved"] == 1
        assert clip["title"] == "Web Approved"
    finally:
        queue.stop_server()
