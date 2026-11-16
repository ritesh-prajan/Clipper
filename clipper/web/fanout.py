"""Multi-account publishing fan-out engine.

Takes an approved clip and fans it out to multiple accounts × platforms,
respecting per-account daily limits, minimum gaps, jitter, dry-run,
and idempotency (never post the same clip to the same account+platform twice).
"""

import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from clipper.openshorts_client import OpenShortsClient, SocialError
from clipper.web.db_web import WebDatabase

logger = logging.getLogger("clipper.web.fanout")


def _make_client(openshorts_url: str, api_key: str) -> OpenShortsClient:
    return OpenShortsClient(
        base_url=openshorts_url,
        upload_post_api_key=api_key,
    )


def fan_out_post(
    *,
    clip_id: str,
    job_id: str,
    clip_title: str,
    clip_path: Path,
    account_ids: List[str],
    platforms_override: Optional[List[str]],
    title_override: Optional[str],
    caption_override: Optional[str],
    schedule_at: Optional[float],
    dry_run: bool,
    openshorts_url: str,
    db_web: WebDatabase,
    db_clips,  # clipper.db.Database instance
    max_jitter_seconds: float = 0.0,
) -> List[Dict[str, Any]]:
    """Post a clip to multiple accounts and platforms.

    Returns list of post result dicts with keys: account_id, platform, status, error.
    """
    results = []
    accounts = [db_web.get_account(aid) for aid in account_ids]
    accounts = [a for a in accounts if a and a.get("enabled")]

    for account in accounts:
        account_id = account["id"]
        platforms = platforms_override if platforms_override else account.get("platforms_enabled", [])

        # Jitter between accounts to avoid spam signal
        if max_jitter_seconds > 0:
            jitter = random.uniform(0, max_jitter_seconds)
            time.sleep(jitter)

        for platform in platforms:
            if platform == "tiktok" and "tiktok" not in account.get("platforms_enabled", []):
                continue  # skip disabled platform for account

            # Idempotency check
            if db_web.is_posted_v2(clip_id, account_id, platform):
                logger.info("Skip (already posted): clip=%s account=%s platform=%s",
                            clip_id[:8], account_id[:8], platform)
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "already_posted", "error": None})
                continue

            # Daily limit check
            daily_limit = account.get(f"daily_limit_{platform}", 10)
            today_count = db_web.count_posts_v2_today(account_id, platform)
            if today_count >= daily_limit:
                logger.warning("Daily limit hit for account=%s platform=%s (%d/%d)",
                               account_id[:8], platform, today_count, daily_limit)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="skipped",
                                       error=f"daily limit {daily_limit} reached")
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "skipped", "error": "daily limit reached"})
                continue

            # Minimum gap check
            min_gap = account.get("min_gap_seconds", 300)
            last_t = db_web.last_post_time_v2(account_id, platform)
            if last_t is not None and (time.time() - last_t) < min_gap:
                need = min_gap - (time.time() - last_t)
                logger.info("Gap cooldown active for account=%s platform=%s (%.0fs remaining)",
                            account_id[:8], platform, need)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="cooldown",
                                       error=f"gap cooldown: {need:.0f}s remaining")
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "cooldown", "error": f"gap cooldown: {need:.0f}s"})
                continue

            if dry_run:
                logger.info("[DRY RUN] Would post clip=%s to account=%s platform=%s",
                            clip_id[:8], account_id[:8], platform)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="dry_run")
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "dry_run", "error": None})
                continue

            # Build caption with account suffix
            caption_suffix = account.get("caption_suffix", "")
            final_title = (title_override or clip_title)[:100]
            base_caption = caption_override or clip_title
            final_caption = f"{base_caption} {caption_suffix}".strip()[:2200]

            # Decrypt API key
            try:
                from clipper.web.crypto import decrypt_key
                raw_key = decrypt_key(account["upload_post_api_key_enc"])
            except Exception as e:
                logger.error("Cannot decrypt API key for account %s: %s", account_id[:8], e)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="failed",
                                       error="key decryption failed")
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "failed", "error": "key decryption failed"})
                continue

            # Execute post via OpenShorts
            try:
                client = _make_client(openshorts_url, raw_key)

                # Build scheduled_date if set
                scheduled_date = None
                if schedule_at:
                    from datetime import datetime, timezone as tz
                    scheduled_date = datetime.fromtimestamp(
                        schedule_at, tz=tz.utc
                    ).isoformat()

                resp = client.post_to_social(
                    job_id=job_id,
                    clip_index=0,
                    platforms=[platform],
                    title=final_title,
                    description=final_caption,
                    scheduled_date=scheduled_date,
                    timezone=account.get("timezone", "UTC"),
                    api_key=raw_key,
                    user_id=account.get("profile_name"),
                )
                request_id = resp.get("request_id", "")
                now = time.time()
                db_web.upsert_post_v2(
                    clip_id, account_id, platform,
                    status="posted",
                    request_id=request_id,
                    posted_at=now,
                )
                logger.info("Posted clip=%s account=%s platform=%s request_id=%s",
                            clip_id[:8], account_id[:8], platform, request_id)
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "posted", "error": None, "request_id": request_id})
                client.close()

            except SocialError as e:
                err_str = str(e)
                # Isolate TikTok — never block YouTube/Instagram
                if platform == "tiktok":
                    logger.warning("TikTok post failed (isolated): %s", err_str)
                else:
                    logger.error("Failed to post account=%s platform=%s: %s",
                                 account_id[:8], platform, err_str)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="failed", error=err_str)
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "failed", "error": err_str})
            except Exception as e:
                err_str = str(e)
                logger.error("Unexpected error posting account=%s platform=%s: %s",
                             account_id[:8], platform, err_str, exc_info=True)
                db_web.upsert_post_v2(clip_id, account_id, platform, status="failed", error=err_str)
                results.append({"account_id": account_id, "platform": platform,
                                 "status": "failed", "error": err_str})

    return results


class PublishScheduler:
    """Background thread that fires off scheduled posts when their time comes."""

    def __init__(self, db_web: WebDatabase, db_clips, openshorts_url: str, check_interval: float = 30.0):
        self.db_web = db_web
        self.db_clips = db_clips
        self.openshorts_url = openshorts_url
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="PublishScheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        while not self._stop_event.wait(self.check_interval):
            try:
                self._fire_due_schedules()
            except Exception as e:
                logger.error("Scheduler loop error: %s", e, exc_info=True)

    def _fire_due_schedules(self) -> None:
        now = time.time()
        due = self.db_web.list_posts_v2(status="scheduled")
        for post in due:
            sched = post.get("scheduled_at")
            if sched and sched <= now:
                clip = self.db_clips.get_clip(post["clip_id"])
                if not clip:
                    continue
                acc = self.db_web.get_account(post["account_id"])
                if not acc:
                    continue
                try:
                    from clipper.web.crypto import decrypt_key
                    raw_key = decrypt_key(acc["upload_post_api_key_enc"])
                    client = _make_client(self.openshorts_url, raw_key)
                    resp = client.post_to_social(
                        job_id=clip["job_id"],
                        clip_index=0,
                        platforms=[post["platform"]],
                        title=clip["title"],
                        api_key=raw_key,
                        user_id=acc.get("profile_name"),
                    )
                    request_id = resp.get("request_id", "")
                    self.db_web.upsert_post_v2(
                        post["clip_id"], post["account_id"], post["platform"],
                        status="posted", request_id=request_id, posted_at=now,
                    )
                    client.close()
                except Exception as e:
                    logger.error("Scheduled post failed: %s", e)
                    self.db_web.upsert_post_v2(
                        post["clip_id"], post["account_id"], post["platform"],
                        status="failed", error=str(e),
                    )
