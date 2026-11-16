"""Comprehensive unit and integration tests for the Clipper Web API."""

import io
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from clipper.config import AppConfig
from clipper.db import Database
from clipper.web.app import create_app
from clipper.web.crypto import decrypt_key, encrypt_key, mask_key
from clipper.web.db_web import WebDatabase
from clipper.web.fanout import fan_out_post


@pytest.fixture
def temp_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_file = tmp_path / "test_pipeline.db"
        output_dir = tmp_path / "live_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "review").mkdir(parents=True, exist_ok=True)
        (output_dir / "shorts").mkdir(parents=True, exist_ok=True)
        yield {
            "tmp_path": tmp_path,
            "db_file": db_file,
            "output_dir": output_dir,
        }


@pytest.fixture
def app_and_client(temp_env):
    app = create_app(
        output_dir=temp_env["output_dir"],
        db_path=temp_env["db_file"],
        bind_host="127.0.0.1",
    )
    client = TestClient(app)
    return {
        "app": app,
        "client": client,
        "db_clips": app.state.db_clips,
        "db_web": app.state.db_web,
        "output_dir": temp_env["output_dir"],
    }


# ── Crypto Tests ─────────────────────────────────────────────────────────────

def test_crypto_encrypt_decrypt():
    secret = "my_super_secret_upload_post_key_12345"
    enc = encrypt_key(secret)
    assert enc != secret
    assert decrypt_key(enc) == secret


def test_key_masking():
    secret = "sk_live_abcdef1234567890"
    masked = mask_key(secret)
    assert "7890" in masked
    assert "abcdef" not in masked
    assert masked.startswith("••••••••")


# ── Accounts API Tests ───────────────────────────────────────────────────────

def test_account_crud_and_masking(app_and_client):
    client = app_and_client["client"]
    raw_key = "up_live_sec_key_xyz9876"

    # Create account
    res = client.post("/api/accounts", json={
        "label": "Main YouTube Account",
        "upload_post_api_key": raw_key,
        "profile_name": "yt_main",
        "platforms_enabled": ["youtube", "instagram"],
        "daily_limit_youtube": 5,
        "daily_limit_instagram": 3,
        "min_gap_seconds": 120,
    })
    assert res.status_code == 201
    data = res.json()
    account_id = data["id"]
    assert data["label"] == "Main YouTube Account"
    # CRITICAL: API key must NEVER be in response, only masked
    assert raw_key not in json.dumps(data)
    assert data["upload_post_api_key_masked"].endswith("9876")

    # List accounts
    res = client.get("/api/accounts")
    assert res.status_code == 200
    accounts = res.json()
    assert len(accounts) == 1
    assert raw_key not in json.dumps(accounts)

    # Update account
    res = client.patch(f"/api/accounts/{account_id}", json={
        "daily_limit_youtube": 8,
    })
    assert res.status_code == 200
    assert res.json()["daily_limit_youtube"] == 8

    # Delete account
    res = client.delete(f"/api/accounts/{account_id}")
    assert res.status_code == 204
    assert len(client.get("/api/accounts").json()) == 0


def test_account_test_connection_mock(app_and_client):
    client = app_and_client["client"]
    res = client.post("/api/accounts", json={
        "label": "Test Acc",
        "upload_post_api_key": "test_key_123",
        "profile_name": "test_user",
        "platforms_enabled": ["youtube"],
    })
    acc_id = res.json()["id"]

    with patch("clipper.openshorts_client.OpenShortsClient.get_social_user") as mock_user:
        mock_user.return_value = {
            "profiles": [
                {"username": "test_user", "connected": ["youtube", "instagram"]}
            ]
        }
        res = client.post(f"/api/accounts/{acc_id}/test")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert len(data["profiles"]) == 1
        assert "youtube" in data["profiles"][0]["connected"]


# ── Sources API Tests ────────────────────────────────────────────────────────

def test_source_crud(app_and_client):
    client = app_and_client["client"]
    res = client.post("/api/sources", json={
        "url": "https://youtu.be/sample123",
        "label": "Test Stream",
        "chunk_seconds": 90,
        "overlap_seconds": 15,
        "i_own_or_have_permission": True,
    })
    assert res.status_code == 201
    source_id = res.json()["id"]
    assert res.json()["i_own_or_have_permission"] is True

    # Get source
    res = client.get(f"/api/sources/{source_id}")
    assert res.status_code == 200
    assert res.json()["label"] == "Test Stream"

    # Update source
    res = client.patch(f"/api/sources/{source_id}", json={"label": "Updated Stream"})
    assert res.status_code == 200
    assert res.json()["label"] == "Updated Stream"

    # Delete source
    res = client.delete(f"/api/sources/{source_id}")
    assert res.status_code == 204


def test_source_ownership_gate(app_and_client):
    client = app_and_client["client"]
    # Create source with i_own_or_have_permission = False
    res = client.post("/api/sources", json={
        "url": "https://youtu.be/unlicensed",
        "i_own_or_have_permission": False,
    })
    source_id = res.json()["id"]

    # Attempting to start the pipeline must be rejected by ownership gate (HTTP 403)
    res = client.post(f"/api/sources/{source_id}/start")
    assert res.status_code == 403
    assert "Ownership gate" in res.json()["detail"]


def test_source_video_upload(app_and_client):
    client = app_and_client["client"]
    fake_video_bytes = b"fake MP4 video header and content bytes"
    file = ("sample_upload.mp4", io.BytesIO(fake_video_bytes), "video/mp4")

    res = client.post(
        "/api/sources/upload",
        files={"file": file},
        data={
            "label": "Uploaded Test Video",
            "chunk_seconds": 60,
            "overlap_seconds": 10,
            "i_own_or_have_permission": "true",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["label"] == "Uploaded Test Video"
    assert Path(data["url"]).exists()


# ── Clips & Approval Tests ───────────────────────────────────────────────────

def test_clips_approval_and_rejection(app_and_client):
    client = app_and_client["client"]
    db_clips = app_and_client["db_clips"]
    output_dir = app_and_client["output_dir"]

    # Stage a fake clip in review directory
    clip_file = output_dir / "review" / "test_clip_001.mp4"
    clip_file.write_bytes(b"dummy mp4 video bytes")

    clip_id = "test-clip-uuid-1"
    db_clips.upsert_clip(
        clip_id=clip_id,
        job_id="job-123",
        title="Epic GTA 6 Stunt",
        path=str(clip_file),
        approved=0,
    )

    # Verify pending
    pending = client.get("/api/clips?status=pending").json()
    assert any(c["id"] == clip_id for c in pending)

    # Approve clip
    res = client.post(f"/api/clips/{clip_id}/approve", json={"new_title": "Approved GTA 6 Stunt"})
    assert res.status_code == 200
    assert res.json()["approved"] == 1
    assert res.json()["title"] == "Approved GTA 6 Stunt"

    # Verify moved to shorts/
    assert (output_dir / "shorts" / "test_clip_001.mp4").exists()

    # Reject another clip
    clip_file2 = output_dir / "review" / "test_clip_002.mp4"
    clip_file2.write_bytes(b"dummy mp4 video bytes 2")
    clip_id2 = "test-clip-uuid-2"
    db_clips.upsert_clip(
        clip_id=clip_id2,
        job_id="job-123",
        title="Boring clip",
        path=str(clip_file2),
        approved=0,
    )
    res = client.post(f"/api/clips/{clip_id2}/reject")
    assert res.status_code == 200
    assert res.json()["approved"] == -1


def test_bulk_clip_approval(app_and_client):
    client = app_and_client["client"]
    db_clips = app_and_client["db_clips"]
    output_dir = app_and_client["output_dir"]

    for i in range(3):
        f = output_dir / "review" / f"bulk_{i}.mp4"
        f.write_bytes(b"content")
        db_clips.upsert_clip(
            clip_id=f"bulk-{i}",
            job_id="job-bulk",
            title=f"Bulk {i}",
            path=str(f),
            approved=0,
        )

    res = client.post("/api/clips/bulk", json={
        "clip_ids": ["bulk-0", "bulk-1", "bulk-2"],
        "action": "approve",
    })
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 3
    assert all(r["ok"] for r in results)


# ── Multi-Account Fan-Out & Idempotency Tests ─────────────────────────────────

def test_multi_account_fanout_and_idempotency(app_and_client):
    db_web = app_and_client["db_web"]
    db_clips = app_and_client["db_clips"]
    output_dir = app_and_client["output_dir"]

    # Setup 2 accounts
    key1 = encrypt_key("key_acc_1")
    key2 = encrypt_key("key_acc_2")
    acc1_id = db_web.create_account("Acc 1", key1, platforms_enabled=["youtube", "instagram"])
    acc2_id = db_web.create_account("Acc 2", key2, platforms_enabled=["youtube", "tiktok"])

    # Setup approved clip
    clip_path = output_dir / "shorts" / "fanout_test.mp4"
    clip_path.write_bytes(b"test video data")
    clip_id = "clip-fanout-01"
    db_clips.upsert_clip(
        clip_id=clip_id,
        job_id="job-fanout",
        title="Viral Moment",
        path=str(clip_path),
        approved=1,
    )

    # Mock OpenShorts social post
    with patch("clipper.openshorts_client.OpenShortsClient.post_to_social") as mock_post:
        mock_post.return_value = {"request_id": "req-xyz-123"}

        # 1. Fan out to both accounts
        results = fan_out_post(
            clip_id=clip_id,
            job_id="job-fanout",
            clip_title="Viral Moment",
            clip_path=clip_path,
            account_ids=[acc1_id, acc2_id],
            platforms_override=None,
            title_override=None,
            caption_override=None,
            schedule_at=None,
            dry_run=False,
            openshorts_url="http://localhost:8000",
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=0.0,
        )

        assert len(results) == 4  # acc1 (youtube, instagram) + acc2 (youtube, tiktok)
        posted_statuses = [r["status"] for r in results]
        assert posted_statuses == ["posted", "posted", "posted", "posted"]

        # 2. Idempotency test: post the exact same clip again -> must return 'already_posted'
        results2 = fan_out_post(
            clip_id=clip_id,
            job_id="job-fanout",
            clip_title="Viral Moment",
            clip_path=clip_path,
            account_ids=[acc1_id, acc2_id],
            platforms_override=None,
            title_override=None,
            caption_override=None,
            schedule_at=None,
            dry_run=False,
            openshorts_url="http://localhost:8000",
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=0.0,
        )
        assert all(r["status"] == "already_posted" for r in results2)


def test_one_account_failure_does_not_block_others(app_and_client):
    db_web = app_and_client["db_web"]
    db_clips = app_and_client["db_clips"]
    output_dir = app_and_client["output_dir"]

    # Setup 2 accounts
    key1 = encrypt_key("bad_key_acc_1")
    key2 = encrypt_key("good_key_acc_2")
    acc1_id = db_web.create_account("Failing Acc", key1, platforms_enabled=["tiktok"])
    acc2_id = db_web.create_account("Healthy Acc", key2, platforms_enabled=["youtube"])

    clip_path = output_dir / "shorts" / "isolation_test.mp4"
    clip_path.write_bytes(b"test video data")
    clip_id = "clip-isolate-01"
    db_clips.upsert_clip(
        clip_id=clip_id,
        job_id="job-isolate",
        title="Isolation Test",
        path=str(clip_path),
        approved=1,
    )

    from clipper.openshorts_client import SocialError

    def mock_post_side_effect(**kwargs):
        if kwargs.get("api_key") == "bad_key_acc_1":
            raise SocialError("TikTok token expired / unavailable in region")
        return {"request_id": "req-good-123"}

    with patch("clipper.openshorts_client.OpenShortsClient.post_to_social", side_effect=mock_post_side_effect):
        results = fan_out_post(
            clip_id=clip_id,
            job_id="job-isolate",
            clip_title="Isolation Test",
            clip_path=clip_path,
            account_ids=[acc1_id, acc2_id],
            platforms_override=None,
            title_override=None,
            caption_override=None,
            schedule_at=None,
            dry_run=False,
            openshorts_url="http://localhost:8000",
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=0.0,
        )

        acc1_res = next(r for r in results if r["account_id"] == acc1_id)
        acc2_res = next(r for r in results if r["account_id"] == acc2_id)

        # Acc 1 fails, but Acc 2 must SUCCEED!
        assert acc1_res["status"] == "failed"
        assert "TikTok token expired" in acc1_res["error"]
        assert acc2_res["status"] == "posted"


def test_daily_limit_and_min_gap_enforcement(app_and_client):
    db_web = app_and_client["db_web"]
    db_clips = app_and_client["db_clips"]
    output_dir = app_and_client["output_dir"]

    # Acc with daily_limit_youtube = 1
    key = encrypt_key("key_rate")
    acc_id = db_web.create_account(
        "Rate Limited Acc",
        key,
        platforms_enabled=["youtube"],
        daily_limit_youtube=1,
        min_gap_seconds=300,
    )

    clip_path = output_dir / "shorts" / "rate_test.mp4"
    clip_path.write_bytes(b"test video data")

    clip1 = "clip-rate-1"
    clip2 = "clip-rate-2"
    db_clips.upsert_clip(clip_id=clip1, job_id="j1", title="Clip 1", path=str(clip_path), approved=1)
    db_clips.upsert_clip(clip_id=clip2, job_id="j2", title="Clip 2", path=str(clip_path), approved=1)

    with patch("clipper.openshorts_client.OpenShortsClient.post_to_social") as mock_post:
        mock_post.return_value = {"request_id": "req-1"}

        # First post succeeds
        r1 = fan_out_post(
            clip_id=clip1,
            job_id="j1",
            clip_title="Clip 1",
            clip_path=clip_path,
            account_ids=[acc_id],
            platforms_override=["youtube"],
            title_override=None,
            caption_override=None,
            schedule_at=None,
            dry_run=False,
            openshorts_url="http://localhost:8000",
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=0.0,
        )
        assert r1[0]["status"] == "posted"

        # Second post immediately hit by daily limit or min_gap
        r2 = fan_out_post(
            clip_id=clip2,
            job_id="j2",
            clip_title="Clip 2",
            clip_path=clip_path,
            account_ids=[acc_id],
            platforms_override=["youtube"],
            title_override=None,
            caption_override=None,
            schedule_at=None,
            dry_run=False,
            openshorts_url="http://localhost:8000",
            db_web=db_web,
            db_clips=db_clips,
            max_jitter_seconds=0.0,
        )
        assert r2[0]["status"] in ("skipped", "cooldown")


# ── Spend Cap Tests ──────────────────────────────────────────────────────────

def test_gemini_spend_cap_enforcement(temp_env):
    from clipper.processor import ClipProcessor

    config = AppConfig.load(
        output_dir=temp_env["output_dir"],
        gemini_spend_cap_usd=0.05,  # $0.05 cap
    )
    db = Database(temp_env["db_file"])
    mock_client = MagicMock()

    processor = ClipProcessor(config=config, db=db, client=mock_client)
    processor.total_gemini_spend = 0.06  # Spend already over cap

    dummy_chunk = temp_env["output_dir"] / "chunk_0099.mp4"
    dummy_chunk.write_bytes(b"dummy chunk data")

    # Calling process_chunk must halt and NOT upload to OpenShorts
    processor.process_chunk(dummy_chunk)

    mock_client.create_upload_slot.assert_not_called()
    chunk_row = db.get_chunk("chunk_0099")
    assert chunk_row["status"] == "spend_cap_paused"


# ── Settings & Password Auth Tests ───────────────────────────────────────────

def test_settings_api(app_and_client):
    client = app_and_client["client"]
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "openshorts_url" in data
    assert "max_disk_gb" in data
    assert "gemini_spend_cap_usd" in data

    # Update settings
    res = client.put("/api/settings", json={
        "max_disk_gb": 50.0,
        "gemini_spend_cap_usd": 25.0,
        "dry_run": True,
    })
    assert res.status_code == 200
    updated = res.json()
    assert updated["max_disk_gb"] == 50.0
    assert updated["gemini_spend_cap_usd"] == 25.0
    assert updated["dry_run"] is True


def test_dashboard_api(app_and_client):
    client = app_and_client["client"]
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    d = res.json()
    assert "total_chunks" in d
    assert "total_clips" in d
    assert "posts_today" in d
    assert "disk_used_gb" in d
    assert "gemini_spend_usd" in d
