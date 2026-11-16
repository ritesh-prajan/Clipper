"""Unit tests for OpenShortsClient."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_httpx import HTTPXMock
from clipper.openshorts_client import (
    OpenShortsClient,
    PollError,
    ProcessError,
    SocialError,
    UploadError,
)


def test_create_upload_slot(httpx_mock: HTTPXMock):
    """Verify create_upload_slot sends correct body and returns slot dictionary."""
    httpx_mock.add_response(
        method="POST",
        url="http://testserver:8000/api/uploads",
        json={
            "upload_id": "slot_123",
            "upload_url": "http://testserver:8000/api/uploads/slot_123",
            "method": "PUT",
            "max_mb": 2048,
            "expires_in": 21600,
            "hint": "PUT bytes",
        },
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        res = client.create_upload_slot("test_chunk.mp4")

    assert res["upload_id"] == "slot_123"
    assert res["upload_url"] == "http://testserver:8000/api/uploads/slot_123"

    req = httpx_mock.get_request()
    assert req is not None
    assert json.loads(req.content.decode("utf-8")) == {"filename": "test_chunk.mp4"}


def test_create_upload_slot_malformed_response(httpx_mock: HTTPXMock):
    """Verify create_upload_slot raises UploadError when response is missing required fields."""
    httpx_mock.add_response(
        method="POST",
        url="http://testserver:8000/api/uploads",
        json={"wrong_field": "something"},
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        with pytest.raises(UploadError, match="Missing required fields"):
            client.create_upload_slot("test.mp4")


def test_stream_upload_file_in_chunks(httpx_mock: HTTPXMock, sample_video_file: Path):
    """Verify stream_upload_file streams in chunks without reading the whole file into RAM."""
    httpx_mock.add_response(
        method="PUT",
        url="http://testserver:8000/api/uploads/slot_123",
        json={"upload_id": "slot_123", "bytes": 1048, "duration_seconds": 10.5},
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        # Spy on file read calls
        with patch("builtins.open", side_effect=open) as mock_open:
            res = client.stream_upload_file(
                "http://testserver:8000/api/uploads/slot_123",
                sample_video_file,
            )

    assert res["upload_id"] == "slot_123"
    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers["Content-Type"] == "video/mp4"


def test_trigger_process_correct_body(httpx_mock: HTTPXMock):
    """Verify trigger_process sends confirmed schema fields to /api/process."""
    httpx_mock.add_response(
        method="POST",
        url="http://testserver:8000/api/process",
        json={"job_id": "job_abc", "status": "queued"},
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        job_id = client.trigger_process(
            upload_id="upload_456",
            acknowledged=True,
            output_format="vertical",
            layouts=["split"],
            captions="true",
        )

    assert job_id == "job_abc"
    req = httpx_mock.get_request()
    body = json.loads(req.content.decode("utf-8"))
    assert body["upload_id"] == "upload_456"
    assert body["acknowledged"] is True
    assert body["output_format"] == "vertical"
    assert body["layouts"] == ["split"]
    assert body["captions"] == "true"


def test_trigger_process_error(httpx_mock: HTTPXMock):
    """Verify trigger_process raises ProcessError on HTTP 400."""
    httpx_mock.add_response(
        method="POST",
        url="http://testserver:8000/api/process",
        text="Invalid parameters",
        status_code=400,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        with pytest.raises(ProcessError, match="Failed to queue job"):
            client.trigger_process("upload_xyz")


def test_poll_status_completed(httpx_mock: HTTPXMock):
    """Verify poll_status returns full result payload."""
    httpx_mock.add_response(
        method="GET",
        url="http://testserver:8000/api/status/job_123",
        json={
            "status": "completed",
            "logs": ["Step 1 done", "Step 2 done"],
            "result": {"clips": [{"title": "Epic Clip", "video_url": "/videos/123/clip1.mp4"}]},
        },
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        status = client.poll_status("job_123")

    assert status["status"] == "completed"
    assert len(status["result"]["clips"]) == 1


def test_poll_status_not_found(httpx_mock: HTTPXMock):
    """Verify poll_status raises PollError when job does not exist."""
    httpx_mock.add_response(
        method="GET",
        url="http://testserver:8000/api/status/job_unknown",
        status_code=404,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        with pytest.raises(PollError, match="Job not found"):
            client.poll_status("job_unknown")


def test_post_to_social_exact_body(httpx_mock: HTTPXMock):
    """Verify post_to_social sends exact SocialPostRequest schema from app.py."""
    httpx_mock.add_response(
        method="POST",
        url="http://testserver:8000/api/social/post",
        json={"request_id": "req_social_999"},
        status_code=200,
    )

    with OpenShortsClient(base_url="http://testserver:8000") as client:
        resp = client.post_to_social(
            job_id="job_123",
            clip_index=0,
            platforms=["youtube", "tiktok"],
            title="Crazy Moment",
            caption="Check this out!",
            hashtags=["gaming", "viral"],
        )

    assert resp["request_id"] == "req_social_999"
    req = httpx_mock.get_request()
    body = json.loads(req.content.decode("utf-8"))
    assert body["job_id"] == "job_123"
    assert body["clip_index"] == 0
    assert body["platforms"] == ["youtube", "tiktok"]
    assert body["title"] == "Crazy Moment"
    assert "#gaming" in body["description"]
    assert "#viral" in body["description"]


def test_post_to_social_missing_job_id():
    """Verify post_to_social raises SocialError if job_id is missing."""
    with OpenShortsClient(base_url="http://testserver:8000") as client:
        with pytest.raises(SocialError, match="requires a valid 'job_id'"):
            client.post_to_social(job_id=None, platform="youtube")
