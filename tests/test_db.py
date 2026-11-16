"""Unit tests for Database (clipper/db.py) — atomicity, concurrency, and resume_state."""

import json
import threading
import time
from pathlib import Path

import pytest

from clipper.db import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Return a fresh Database instance for each test."""
    return Database(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def test_schema_created(db: Database) -> None:
    """Verify all tables exist after initialisation."""
    with db._connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"chunks", "jobs", "clips", "posts", "posted_hashes"} <= tables


# ---------------------------------------------------------------------------
# upsert_chunk
# ---------------------------------------------------------------------------


def test_upsert_chunk_insert(db: Database) -> None:
    """upsert_chunk creates a new row on first call."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    row = db.get_chunk("c1")
    assert row is not None
    assert row["path"] == "/tmp/c1.mp4"
    assert row["status"] == "pending"


def test_upsert_chunk_update(db: Database) -> None:
    """upsert_chunk updates status on second call."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_chunk("c1", "/tmp/c1.mp4", "completed")
    assert db.get_chunk("c1")["status"] == "completed"


def test_upsert_chunk_missing(db: Database) -> None:
    """get_chunk returns None for unknown ids."""
    assert db.get_chunk("nonexistent") is None


# ---------------------------------------------------------------------------
# upsert_job
# ---------------------------------------------------------------------------


def test_upsert_job_insert(db: Database) -> None:
    """upsert_job creates a job row with correct status."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "queued")
    row = db.get_job("j1")
    assert row is not None
    assert row["status"] == "queued"
    assert row["result_json"] is None


def test_upsert_job_stores_result_json(db: Database) -> None:
    """upsert_job serialises dict result_json and coalesces on update."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    result = {"clips": [{"title": "Clip 1"}]}
    db.upsert_job("j1", "c1", "completed", result_json=result)
    row = db.get_job("j1")
    assert row["result_json"] == json.dumps(result)


def test_upsert_job_coalesce_result(db: Database) -> None:
    """Updating status does not wipe result_json when new value is None."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed", result_json={"clips": []})
    db.upsert_job("j1", "c1", "failed", result_json=None)
    row = db.get_job("j1")
    # result_json should still hold the original value
    assert row["result_json"] is not None


# ---------------------------------------------------------------------------
# upsert_clip / get_clip / get_pending_clips
# ---------------------------------------------------------------------------


def test_upsert_clip_insert(db: Database) -> None:
    """upsert_clip creates clip row with defaults."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip1", "j1", "Title A", "/tmp/clip1.mp4", approved=0)
    clip = db.get_clip("clip1")
    assert clip["title"] == "Title A"
    assert clip["approved"] == 0
    assert clip["posted_platforms"] == []


def test_upsert_clip_posted_platforms_round_trips(db: Database) -> None:
    """posted_platforms is returned as a list, not a JSON string."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip2", "j1", "Title B", "/tmp/clip2.mp4", posted_platforms=["youtube", "tiktok"])
    clip = db.get_clip("clip2")
    assert clip["posted_platforms"] == ["youtube", "tiktok"]


def test_get_pending_clips_returns_unapproved(db: Database) -> None:
    """get_pending_clips only returns clips with approved == 0."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip_pending", "j1", "Pending", "/tmp/pending.mp4", approved=0)
    db.upsert_clip("clip_approved", "j1", "Approved", "/tmp/approved.mp4", approved=1)
    db.upsert_clip("clip_rejected", "j1", "Rejected", "/tmp/rejected.mp4", approved=-1)

    pending = db.get_pending_clips()
    ids = [p["id"] for p in pending]
    assert "clip_pending" in ids
    assert "clip_approved" not in ids
    assert "clip_rejected" not in ids


# ---------------------------------------------------------------------------
# mark_clip_approved / mark_clip_rejected
# ---------------------------------------------------------------------------


def test_mark_clip_approved(db: Database) -> None:
    """mark_clip_approved sets approved=1 and optionally updates path."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip3", "j1", "Title C", "/tmp/review/clip3.mp4", approved=0)
    db.mark_clip_approved("clip3", new_path="/tmp/shorts/clip3.mp4")
    clip = db.get_clip("clip3")
    assert clip["approved"] == 1
    assert clip["path"] == "/tmp/shorts/clip3.mp4"


def test_mark_clip_rejected(db: Database) -> None:
    """mark_clip_rejected sets approved=-1."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip4", "j1", "Title D", "/tmp/clip4.mp4", approved=0)
    db.mark_clip_rejected("clip4")
    assert db.get_clip("clip4")["approved"] == -1


# ---------------------------------------------------------------------------
# upsert_post / is_already_posted / mark_posted
# ---------------------------------------------------------------------------


def test_upsert_post(db: Database) -> None:
    """upsert_post stores a posting record."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("clip5", "j1", "Title E", "/tmp/clip5.mp4")
    db.upsert_post("post1", "clip5", "youtube", "posted", remote_id="req_abc")
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id='post1'").fetchone()
    assert row is not None
    assert dict(row)["status"] == "posted"


def test_is_already_posted_false(db: Database) -> None:
    """is_already_posted returns False when no hash/platform match exists."""
    assert db.is_already_posted("abc123", "tiktok") is False


def test_is_already_posted_true_after_mark(db: Database) -> None:
    """is_already_posted returns True after mark_posted is called."""
    db.mark_posted("hashxyz", "instagram")
    assert db.is_already_posted("hashxyz", "instagram") is True
    # Different platform same hash -> False
    assert db.is_already_posted("hashxyz", "tiktok") is False


def test_mark_posted_idempotent(db: Database) -> None:
    """Calling mark_posted twice for the same hash/platform does not raise."""
    db.mark_posted("h1", "youtube")
    db.mark_posted("h1", "youtube")  # should not raise
    assert db.is_already_posted("h1", "youtube") is True


# ---------------------------------------------------------------------------
# count_recent_posts / get_last_post_time
# ---------------------------------------------------------------------------


def test_count_recent_posts(db: Database) -> None:
    """count_recent_posts counts only 'posted'/'success' entries within window."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("cl1", "j1", "T1", "/tmp/cl1.mp4")

    db.upsert_post("p1", "cl1", "youtube", "posted", created_at=time.time() - 60)
    db.upsert_post("p2", "cl1", "youtube", "failed", created_at=time.time() - 60)
    db.upsert_post("p3", "cl1", "youtube", "posted", created_at=time.time() - 90000)

    # Only p1 is within 86400s and has status 'posted'
    assert db.count_recent_posts("youtube", window_seconds=86400.0) == 1


def test_get_last_post_time(db: Database) -> None:
    """get_last_post_time returns the most recent 'posted' timestamp."""
    db.upsert_chunk("c1", "/tmp/c1.mp4", "pending")
    db.upsert_job("j1", "c1", "completed")
    db.upsert_clip("cl1", "j1", "T1", "/tmp/cl1.mp4")

    t1 = time.time() - 300
    t2 = time.time() - 100
    db.upsert_post("p1", "cl1", "tiktok", "posted", created_at=t1)
    db.upsert_post("p2", "cl1", "tiktok", "posted", created_at=t2)

    last = db.get_last_post_time("tiktok")
    assert last is not None
    assert abs(last - t2) < 1.0


# ---------------------------------------------------------------------------
# get_processable_chunks
# ---------------------------------------------------------------------------


def test_get_processable_chunks(db: Database) -> None:
    """get_processable_chunks returns only 'pending' or 'recorded' chunks."""
    db.upsert_chunk("c_pending", "/tmp/pending.mp4", "pending")
    db.upsert_chunk("c_recorded", "/tmp/recorded.mp4", "recorded")
    db.upsert_chunk("c_done", "/tmp/done.mp4", "completed")
    db.upsert_chunk("c_failed", "/tmp/failed.mp4", "failed")

    processable = db.get_processable_chunks()
    ids = [r["id"] for r in processable]
    assert "c_pending" in ids
    assert "c_recorded" in ids
    assert "c_done" not in ids
    assert "c_failed" not in ids


# ---------------------------------------------------------------------------
# resume_state
# ---------------------------------------------------------------------------


def test_resume_state_returns_correct_counts(db: Database) -> None:
    """resume_state returns pending chunks, in-flight jobs, and unreviewed clips."""
    db.upsert_chunk("c_active", "/tmp/ca.mp4", "uploaded")
    db.upsert_chunk("c_done", "/tmp/cd.mp4", "completed")
    db.upsert_job("j_active", "c_active", "processing")
    db.upsert_job("j_done", "c_done", "completed")
    db.upsert_clip("clip_pending", "j_done", "P", "/tmp/cp.mp4", approved=0)
    db.upsert_clip("clip_approved", "j_done", "A", "/tmp/ca_clip.mp4", approved=1)

    state = db.resume_state()

    pending_ids = [r["id"] for r in state["pending_chunks"]]
    assert "c_active" in pending_ids
    assert "c_done" not in pending_ids

    active_job_ids = [r["id"] for r in state["active_jobs"]]
    assert "j_active" in active_job_ids
    assert "j_done" not in active_job_ids

    review_ids = [r["id"] for r in state["pending_review"]]
    assert "clip_pending" in review_ids
    assert "clip_approved" not in review_ids

    approved_ids = [r["id"] for r in state["approved_clips"]]
    assert "clip_approved" in approved_ids


# ---------------------------------------------------------------------------
# Concurrency / atomic writes
# ---------------------------------------------------------------------------


def test_concurrent_upserts_do_not_corrupt(tmp_path: Path) -> None:
    """Concurrent upsert_chunk calls from multiple threads must not corrupt the DB."""
    db = Database(tmp_path / "concurrent.db")

    errors: list[Exception] = []

    def insert_many(prefix: str) -> None:
        for i in range(50):
            try:
                db.upsert_chunk(f"{prefix}_{i}", f"/tmp/{prefix}_{i}.mp4", "pending")
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=insert_many, args=(f"t{t}",)) for t in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"Concurrent upserts raised: {errors}"

    all_chunks = db.get_all_chunks()
    assert len(all_chunks) == 250  # 5 threads × 50 rows
