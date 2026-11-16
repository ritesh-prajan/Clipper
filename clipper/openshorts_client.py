"""HTTP Client for OpenShorts REST API endpoints.

All endpoint schemas and fields strictly match OpenShorts app.py:
- POST /api/uploads
- PUT  /api/uploads/{upload_id}
- POST /api/process
- GET  /api/status/{job_id}
- POST /api/social/post
- GET  /api/social/post-status/{request_id}
- GET  /api/social/user
- GET  /api/social/scheduled
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

import httpx

logger = logging.getLogger("clipper.client")


class OpenShortsClientError(Exception):
    """Base exception for OpenShorts client errors."""


class UploadError(OpenShortsClientError):
    """Exception raised when reserving an upload slot or streaming video bytes fails."""


class ProcessError(OpenShortsClientError):
    """Exception raised when triggering video processing fails."""


class PollError(OpenShortsClientError):
    """Exception raised when querying job status fails."""


class JobNotFoundError(PollError):
    """Exception raised when querying job status returns 404 (job deleted or purged)."""


class SocialError(OpenShortsClientError):
    """Exception raised during social media posting or query requests."""


class OpenShortsClient:
    """Synchronous HTTP client for interacting with OpenShorts server endpoints."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        upload_post_api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Initialize the OpenShorts client.

        Args:
            base_url: Base URL of OpenShorts server.
            api_key: Optional OpenShorts Bearer token for cloud mode (never logged).
            upload_post_api_key: Optional Upload-Post key for social endpoints (never logged).
            timeout: Default request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._upload_post_api_key = upload_post_api_key
        self.timeout = timeout

        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenShorts-LiveClipper/0.1.0",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self._upload_post_api_key:
            headers["X-Upload-Post-Key"] = self._upload_post_api_key

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._client.close()

    def __enter__(self) -> "OpenShortsClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def test_connection(self) -> bool:
        """Check if OpenShorts server is reachable via /health.

        Returns:
            True if status code is 200, False otherwise.
        """
        try:
            resp = self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception as e:
            logger.debug("Health check failed for %s: %s", self.base_url, e)
            return False

    def create_upload_slot(self, filename: str) -> Dict[str, Any]:
        """Reserve an upload slot in OpenShorts.

        Endpoint: POST /api/uploads
        Request Body: {"filename": "<filename>"}
        Expected Response:
            {
                "upload_id": str,
                "upload_url": str,
                "method": "PUT",
                "max_mb": int,
                "expires_in": int,
                "hint": str
            }

        Args:
            filename: Name of the video file to be uploaded.

        Returns:
            Dict response with upload_id and upload_url.

        Raises:
            UploadError: If the server returns an error or missing fields.
        """
        logger.info("Reserving upload slot for filename='%s'", filename)
        try:
            resp = self._client.post("/api/uploads", json={"filename": filename})
        except httpx.HTTPError as e:
            raise UploadError(f"Network error requesting upload slot: {e}") from e

        if resp.status_code != 200:
            raise UploadError(
                f"Failed to reserve upload slot (HTTP {resp.status_code}): {resp.text}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise UploadError(f"Malformed JSON response from /api/uploads: {resp.text}") from e

        if not isinstance(data, dict) or "upload_id" not in data or "upload_url" not in data:
            raise UploadError(f"Missing required fields in upload slot response: {data}")

        return data

    def stream_upload_file(self, upload_url: str, file_path: Path) -> Dict[str, Any]:
        """Stream video bytes to the reserved upload slot in 1 MB chunks.

        Endpoint: PUT {upload_url}
        Header: Content-Type: video/mp4
        Expected Response:
            {
                "upload_id": str,
                "bytes": int,
                "duration_seconds": float,
                "hint": str
            }

        Args:
            upload_url: Upload URL returned from create_upload_slot.
            file_path: Path to the MP4 file to upload.

        Returns:
            Dict containing upload details.

        Raises:
            UploadError: If file is missing or server rejects upload.
        """
        file_path = Path(file_path)
        if not file_path.exists() or not file_path.is_file():
            raise UploadError(f"Source video file not found: {file_path}")

        file_size = file_path.stat().st_size
        logger.info("Streaming %s (%.2f MB) to upload slot...", file_path.name, file_size / (1024 * 1024))

        def chunk_generator() -> Generator[bytes, None, None]:
            with open(file_path, "rb") as f:
                while chunk := f.read(1024 * 1024):  # 1 MB chunks
                    yield chunk

        # Resolve relative URL if needed
        target_url = upload_url
        if not target_url.startswith(("http://", "https://")):
            target_url = f"{self.base_url}/{upload_url.lstrip('/')}"

        headers = {"Content-Type": "video/mp4"}
        try:
            # Dedicated streaming request with extended upload timeout
            resp = self._client.put(
                target_url,
                content=chunk_generator(),
                headers=headers,
                timeout=600.0,
            )
        except httpx.HTTPError as e:
            raise UploadError(f"Network error during streaming upload: {e}") from e

        if resp.status_code not in (200, 201, 204):
            raise UploadError(f"Upload failed (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception:
            return {"status": "success", "status_code": resp.status_code}

    def trigger_process(
        self,
        upload_id: str,
        acknowledged: bool = True,
        output_format: str = "vertical",
        layouts: Optional[List[str]] = None,
        captions: Optional[str] = None,
        target_clips: Optional[int] = None,
        clip_min_seconds: Optional[int] = None,
        clip_max_seconds: Optional[int] = None,
        auto_hook: Optional[bool] = None,
        auto_hook_style: Optional[str] = None,
        webhook_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        **extra_fields,
    ) -> str:
        """Trigger OpenShorts moment detection and clipping for an uploaded file.

        Endpoint: POST /api/process
        Body fields confirmed in app.py:
            - upload_id (str)
            - acknowledged (bool)
            - output_format (str: 'vertical' | 'horizontal' | 'square' | 'auto')
            - layouts (list or comma-separated str)
            - captions (str)
            - target_clips (int)
            - clip_min_seconds (int)
            - clip_max_seconds (int)
            - auto_hook (bool)
            - auto_hook_style (str)
            - webhook_url (str)
            - webhook_secret (str)

        Returns:
            Job ID (str).

        Raises:
            ProcessError: If processing fails to start or server returns an error.
        """
        payload: Dict[str, Any] = {
            "upload_id": upload_id,
            "acknowledged": acknowledged,
            "output_format": output_format,
        }

        if layouts is not None:
            payload["layouts"] = layouts
        if captions is not None:
            payload["captions"] = captions
        if target_clips is not None:
            payload["target_clips"] = target_clips
        if clip_min_seconds is not None:
            payload["clip_min_seconds"] = clip_min_seconds
        if clip_max_seconds is not None:
            payload["clip_max_seconds"] = clip_max_seconds
        if auto_hook is not None:
            payload["auto_hook"] = auto_hook
        if auto_hook_style is not None:
            payload["auto_hook_style"] = auto_hook_style
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if webhook_secret is not None:
            payload["webhook_secret"] = webhook_secret

        # Add any explicit extra fields
        payload.update(extra_fields)

        logger.info("Queuing OpenShorts job for upload_id='%s'", upload_id)
        try:
            resp = self._client.post("/api/process", json=payload)
        except httpx.HTTPError as e:
            raise ProcessError(f"Network error queuing job: {e}") from e

        if resp.status_code not in (200, 201, 202):
            raise ProcessError(f"Failed to queue job (HTTP {resp.status_code}): {resp.text}")

        try:
            data = resp.json()
        except Exception as e:
            raise ProcessError(f"Malformed JSON response from /api/process: {resp.text}") from e

        job_id = data.get("job_id")
        if not job_id:
            raise ProcessError(f"Server response missing 'job_id': {data}")

        logger.info("Job successfully queued: job_id='%s'", job_id)
        return str(job_id)

    def poll_status(self, job_id: str) -> Dict[str, Any]:
        """Poll job status and rendered clip results.

        Endpoint: GET /api/status/{job_id}
        Response fields confirmed in app.py:
            - status (str: 'queued' | 'processing' | 'completed' | 'failed')
            - logs (List[str])
            - log_times (List[float])
            - result (Dict: {'clips': [...], 'cost_analysis': ...})
            - queue (Dict or None)
            - partial (bool or None)

        Returns:
            Status response dictionary.

        Raises:
            PollError: If request fails or job is not found.
        """
        try:
            resp = self._client.get(f"/api/status/{job_id}")
        except httpx.HTTPError as e:
            raise PollError(f"Network error polling status for {job_id}: {e}") from e

        if resp.status_code == 404:
            raise JobNotFoundError(f"Job not found: {job_id}")

        if resp.status_code != 200:
            raise PollError(f"Failed to fetch job status (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            raise PollError(f"Malformed JSON response from /api/status/{job_id}: {resp.text}") from e

    def download_clip(self, clip_url: str, dest_path: Path) -> Path:
        """Stream download a rendered clip to disk in 64 KB chunks.

        Args:
            clip_url: Relative (/videos/...) or absolute download URL.
            dest_path: Local filesystem destination path.

        Returns:
            Resolved local Path to the downloaded clip.

        Raises:
            OpenShortsClientError: If download fails.
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        target_url = clip_url
        if not target_url.startswith(("http://", "https://")):
            target_url = f"{self.base_url}/{clip_url.lstrip('/')}"

        logger.info("Downloading clip from %s to %s", target_url, dest_path.name)
        try:
            with self._client.stream("GET", target_url, timeout=120.0) as resp:
                if resp.status_code != 200:
                    raise OpenShortsClientError(
                        f"Failed to download clip (HTTP {resp.status_code}) from {target_url}"
                    )
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
            return dest_path
        except httpx.HTTPError as e:
            raise OpenShortsClientError(f"Network error downloading clip: {e}") from e

    def post_to_social(
        self,
        clip_path: Optional[Path] = None,
        platform: Optional[str] = None,
        title: Optional[str] = None,
        caption: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        schedule_at: Optional[Union[datetime, str]] = None,
        job_id: Optional[str] = None,
        clip_index: int = 0,
        platforms: Optional[List[str]] = None,
        description: Optional[str] = None,
        scheduled_date: Optional[str] = None,
        timezone: str = "UTC",
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publish or schedule a clip to social networks via OpenShorts /api/social/post.

        Endpoint: POST /api/social/post
        Request body schema confirmed in app.py (SocialPostRequest):
            - job_id: str
            - clip_index: int
            - platforms: List[str]
            - title: Optional[str]
            - description: Optional[str]
            - scheduled_date: Optional[str] (ISO-8601)
            - timezone: Optional[str] (default 'UTC')
            - api_key: Optional[str]
            - user_id: Optional[str]

        Returns:
            Upload-Post API response containing request_id.

        Raises:
            SocialError: If posting fails.
        """
        # Resolve platforms list
        target_platforms: List[str] = []
        if platforms:
            target_platforms = list(platforms)
        elif platform:
            target_platforms = [platform]
        else:
            target_platforms = ["upload_post"]

        # Resolve description / caption / hashtags
        final_desc = description
        if final_desc is None:
            parts = []
            if caption:
                parts.append(caption.strip())
            if hashtags:
                parts.extend([f"#{h.strip('#')}" for h in hashtags if h.strip()])
            final_desc = " ".join(parts) if parts else None

        # Resolve scheduled date
        final_sched = scheduled_date
        if final_sched is None and schedule_at is not None:
            if isinstance(schedule_at, datetime):
                final_sched = schedule_at.isoformat()
            else:
                final_sched = str(schedule_at)

        if not job_id:
            raise SocialError("OpenShorts POST /api/social/post requires a valid 'job_id'.")

        payload: Dict[str, Any] = {
            "job_id": job_id,
            "clip_index": clip_index,
            "platforms": target_platforms,
            "timezone": timezone,
        }

        if title is not None:
            payload["title"] = title
        if final_desc is not None:
            payload["description"] = final_desc
        if final_sched is not None:
            payload["scheduled_date"] = final_sched
        if api_key is not None:
            payload["api_key"] = api_key
        elif self._upload_post_api_key:
            payload["api_key"] = self._upload_post_api_key
        if user_id is not None:
            payload["user_id"] = user_id

        logger.info("Publishing clip via /api/social/post (platforms=%s, job_id=%s)", target_platforms, job_id)
        try:
            resp = self._client.post("/api/social/post", json=payload, timeout=120.0)
        except httpx.HTTPError as e:
            raise SocialError(f"Network error during social post: {e}") from e

        if resp.status_code not in (200, 201, 202):
            raise SocialError(f"Social post failed (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            raise SocialError(f"Malformed JSON response from /api/social/post: {resp.text}") from e

    def get_post_status(self, request_id: str) -> Dict[str, Any]:
        """Fetch async upload status for a social post.

        Endpoint: GET /api/social/post-status/{request_id}
        Response schema confirmed in app.py:
            {"status": str, "results": [{"platform": str, "success": bool, "message": str}]}

        Returns:
            Status dictionary.

        Raises:
            SocialError: On failure.
        """
        try:
            resp = self._client.get(f"/api/social/post-status/{request_id}")
        except httpx.HTTPError as e:
            raise SocialError(f"Network error querying post status: {e}") from e

        if resp.status_code != 200:
            raise SocialError(f"Failed to fetch post status (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            raise SocialError(f"Malformed JSON response for post-status: {resp.text}") from e

    def get_social_user(self) -> Dict[str, Any]:
        """Fetch connected social profiles from OpenShorts / Upload-Post.

        Endpoint: GET /api/social/user
        Response schema confirmed in app.py:
            {"profiles": [{"username": str, "connected": [str, ...]}]}

        Returns:
            Dictionary containing list of profiles.

        Raises:
            SocialError: On failure.
        """
        try:
            resp = self._client.get("/api/social/user")
        except httpx.HTTPError as e:
            raise SocialError(f"Network error fetching social user: {e}") from e

        if resp.status_code != 200:
            raise SocialError(f"Failed to fetch social user (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            raise SocialError(f"Malformed JSON response from /api/social/user: {resp.text}") from e

    def get_scheduled_posts(self, user: Optional[str] = None) -> Dict[str, Any]:
        """Fetch scheduled posts queue.

        Endpoint: GET /api/social/scheduled
        Query param: user (str, optional)
        Response schema confirmed in app.py:
            {"profile_username": str, "scheduled_posts": list}

        Returns:
            Scheduled posts dictionary.

        Raises:
            SocialError: On failure.
        """
        params = {}
        if user:
            params["user"] = user

        try:
            resp = self._client.get("/api/social/scheduled", params=params)
        except httpx.HTTPError as e:
            raise SocialError(f"Network error fetching scheduled posts: {e}") from e

        if resp.status_code != 200:
            raise SocialError(f"Failed to fetch scheduled posts (HTTP {resp.status_code}): {resp.text}")

        try:
            return resp.json()
        except Exception as e:
            raise SocialError(f"Malformed JSON response from /api/social/scheduled: {resp.text}") from e
