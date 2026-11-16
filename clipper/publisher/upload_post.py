"""UploadPostPublisher implementation utilizing OpenShorts /api/social/post relay."""

import hashlib
import logging
import time
import uuid
from typing import Dict, List, Optional

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import OpenShortsClient, SocialError
from clipper.publisher import ClipRecord, Publisher

logger = logging.getLogger("clipper.publisher.upload_post")

# Platform length limitations
MAX_YOUTUBE_TITLE_LEN = 100
MAX_YOUTUBE_DESC_LEN = 5000
MAX_TIKTOK_TITLE_LEN = 150
MAX_TIKTOK_DESC_LEN = 2200
MAX_INSTAGRAM_CAPTION_LEN = 2200


def format_title_and_description(
    title: str,
    description: Optional[str],
    platform: str,
) -> tuple[str, str]:
    """Format and truncate title and description according to platform length limits.

    Args:
        title: Raw title string.
        description: Raw description or caption string.
        platform: Platform name ('youtube', 'tiktok', 'instagram', or 'upload_post').

    Returns:
        Tuple of (formatted_title, formatted_description).
    """
    raw_title = title or "Viral Clip"
    raw_desc = description or raw_title

    if platform == "youtube":
        return raw_title[:MAX_YOUTUBE_TITLE_LEN], raw_desc[:MAX_YOUTUBE_DESC_LEN]
    elif platform == "tiktok":
        return raw_title[:MAX_TIKTOK_TITLE_LEN], raw_desc[:MAX_TIKTOK_DESC_LEN]
    elif platform == "instagram":
        return raw_title[:MAX_INSTAGRAM_CAPTION_LEN], raw_desc[:MAX_INSTAGRAM_CAPTION_LEN]
    else:
        # Generic upload_post limits
        return raw_title[:MAX_YOUTUBE_TITLE_LEN], raw_desc[:MAX_INSTAGRAM_CAPTION_LEN]


class UploadPostPublisher(Publisher):
    """Publisher for distributing clips to social channels via Upload-Post."""

    def __init__(self, config: AppConfig, db: Database, client: OpenShortsClient):
        """Initialize the publisher.

        Args:
            config: Application configuration.
            db: SQLite database instance.
            client: OpenShortsClient instance.
        """
        self.config = config
        self.db = db
        self.client = client

    def check_token(self) -> bool:
        """Verify Upload-Post credentials via OpenShorts /api/social/user.

        Returns:
            True if credentials and profiles are valid, False if authentication failed.
        """
        try:
            data = self.client.get_social_user()
            profiles = data.get("profiles") or []
            if not profiles and data.get("error"):
                logger.warning("Upload-Post credentials valid but no profiles found: %s", data.get("error"))
                return False
            logger.info("Upload-Post token validated: %d profile(s) connected.", len(profiles))
            return True
        except SocialError as e:
            logger.warning("⚠️ Upload-Post token validation failed (reauth required): %s", e)
            return False

    def post(self, clip: ClipRecord, dry_run: bool = False) -> str:
        """Publish a clip to all configured platforms with rate limiting and idempotency.

        Returns:
            Remote request ID, 'dry_run', or 'already_posted'.
        """
        # Enforce ownership gate before anything else
        if not self.config.i_own_or_have_permission:
            logger.error("Refusing to publish clip '%s': 'i_own_or_have_permission' is false.", clip.title)
            raise PermissionError("Publishing refused: 'i_own_or_have_permission' must be true in configuration.")

        if dry_run or self.config.dry_run:
            logger.info("[DRY RUN] Would publish '%s' to %s", clip.title, self.config.platforms)
            return "dry_run"

        if not clip.path.exists():
            raise FileNotFoundError(f"Clip video file does not exist: {clip.path}")

        # Compute content hash for idempotency
        content_hash = hashlib.sha256(clip.path.read_bytes()).hexdigest()[:16]

        target_platforms = list(self.config.platforms)
        posted_request_ids = []

        # Process TikTok separately or as part of batch to prevent TikTok failures from breaking other platforms
        for platform in target_platforms:
            # 1. Idempotency check
            if self.db.is_already_posted(content_hash, platform):
                logger.info("Clip '%s' has already been posted to %s. Skipping (idempotent).", clip.title, platform)
                continue

            # 2. Rate limiting check: Daily limit
            daily_limit = self.config.daily_post_limit.get(platform, 10)
            today_count = self.db.count_recent_posts(platform, window_seconds=86400.0)
            if today_count >= daily_limit:
                logger.warning(
                    "Daily post limit reached for %s (%d/%d posts in 24h). Skipping '%s'.",
                    platform,
                    today_count,
                    daily_limit,
                    clip.title,
                )
                continue

            # 3. Rate limiting check: Minimum gap between posts
            last_post_time = self.db.get_last_post_time(platform)
            if last_post_time is not None:
                elapsed = time.time() - last_post_time
                if elapsed < self.config.min_post_gap_seconds:
                    wait_need = self.config.min_post_gap_seconds - elapsed
                    logger.info("Platform %s cooldown active (needs %.1fs more). Skipping '%s' for now.", platform, wait_need, clip.title)
                    continue

            # 4. Token validation check
            if not self.check_token():
                logger.error("Token invalid or expired for %s. Skipping post.", platform)
                continue

            # 5. Format title and description per platform
            formatted_title, formatted_desc = format_title_and_description(
                title=clip.title,
                description=clip.title,
                platform=platform,
            )

            # 6. Execute social post via OpenShorts client
            # TikTok failures are isolated so other platforms (YouTube, Instagram) still publish
            try:
                logger.info("Posting clip '%s' to %s via OpenShorts /api/social/post...", clip.title, platform)
                resp = self.client.post_to_social(
                    job_id=clip.job_id,
                    clip_index=0,
                    platforms=[platform],
                    title=formatted_title,
                    description=formatted_desc,
                )
                req_id = resp.get("request_id") or str(uuid.uuid4())
                posted_request_ids.append(req_id)

                # Persist post record for idempotency and rate limiting
                post_id = str(uuid.uuid4())
                self.db.upsert_post(
                    post_id=post_id,
                    clip_id=clip.id,
                    platform=platform,
                    status="posted",
                    remote_id=req_id,
                )
                self.db.mark_posted(hash_val=content_hash, platform=platform)
                self.db.mark_clip_posted(clip_id=clip.id, platform=platform)
                logger.info("Successfully initiated post for '%s' on %s (request_id=%s)", clip.title, platform, req_id)

            except SocialError as e:
                post_id = str(uuid.uuid4())
                self.db.upsert_post(
                    post_id=post_id,
                    clip_id=clip.id,
                    platform=platform,
                    status="failed",
                )
                if platform == "tiktok":
                    logger.warning("TikTok posting failed (isolated): %s. Other platforms unaffected.", e)
                else:
                    logger.error("Failed to post to %s: %s", platform, e)

        return posted_request_ids[0] if posted_request_ids else "none_posted"
