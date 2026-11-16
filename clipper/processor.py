"""Clip processing worker pool, queue manager, deduplication, and disk capacity guard."""

import concurrent.futures
import hashlib
import json
import logging
import queue
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from clipper.config import AppConfig
from clipper.db import Database
from clipper.openshorts_client import JobNotFoundError, OpenShortsClient, OpenShortsClientError

logger = logging.getLogger("clipper.processor")

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(title: str, chunk_stem: str, clip_index: int) -> str:
    """Sanitize clip title into a safe, collision-free filename compatible with Windows and POSIX.

    Args:
        title: Raw title string from OpenShorts result.
        chunk_stem: Stem of the originating chunk (e.g. 'chunk_0001').
        clip_index: 0-based or 1-based index of the clip in the batch.

    Returns:
        Safe filename with format: {chunk_stem}_{clip_index}_{sanitized_title}_{short_hash}.mp4
    """
    clean = re.sub(r"[^\w\s-]", "", title or f"clip_{clip_index}").strip()
    clean = re.sub(r"[-\s]+", "_", clean)
    if not clean or clean.upper() in WINDOWS_RESERVED_NAMES:
        clean = f"clip_{clip_index}"

    clean = clean[:60].strip("._")
    # 8-char SHA-256 suffix guarantees uniqueness across duplicates
    short_hash = hashlib.sha256(f"{title}:{chunk_stem}:{clip_index}:{uuid.uuid4().hex[:6]}".encode()).hexdigest()[:8]
    return f"{chunk_stem}_{clip_index}_{clean}_{short_hash}.mp4"


class ClipProcessor:
    """Orchestrates chunk processing jobs, polling, clip extraction, and disk safety."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        client: OpenShortsClient,
    ):
        """Initialize processor with application configuration, state DB, and OpenShorts client.

        Args:
            config: Application configuration.
            db: Database persistence instance.
            client: OpenShorts HTTP client.
        """
        self.config = config
        self.db = db
        self.client = client

        self.shorts_dir = self.config.output_dir / "shorts"
        self.review_dir = self.config.output_dir / "review"
        self.shorts_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)

        self.work_queue: queue.Queue[Path] = queue.Queue()
        self.stop_event = threading.Event()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix="ClipWorker",
        )
        self._worker_threads: List[concurrent.futures.Future] = []
        self._lock = threading.Lock()

        # Track global clip time-windows for deduplication across overlapping segments:
        # List of (global_start_sec, global_end_sec, title)
        self._known_windows: List[Tuple[float, float, str]] = []

    def start_workers(self) -> None:
        """Start the background worker thread pool."""
        logger.info("Starting %d processor worker thread(s)...", self.config.max_workers)
        for i in range(self.config.max_workers):
            future = self._executor.submit(self._worker_loop, i)
            self._worker_threads.append(future)

    def enqueue_chunk(self, chunk_path: Path) -> None:
        """Add a completed chunk path to the processing queue."""
        chunk_id = chunk_path.stem
        # Register chunk in DB if not present
        existing = self.db.get_chunk(chunk_id)
        if not existing:
            self.db.upsert_chunk(chunk_id=chunk_id, path=str(chunk_path), status="pending")
        elif existing["status"] == "completed":
            logger.info("Skipping already completed chunk: %s", chunk_id)
            return

        self.work_queue.put(chunk_path)
        logger.info("Enqueued %s for processing (queue size: %d)", chunk_path.name, self.work_queue.qsize())

    def _worker_loop(self, worker_id: int) -> None:
        """Worker thread entry point continuously pulling chunks from work queue."""
        logger.debug("Worker %d started.", worker_id)
        while not self.stop_event.is_set():
            try:
                chunk_path = self.work_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self.process_chunk(chunk_path)
            except Exception as e:
                logger.error("Unexpected error in worker %d processing %s: %s", worker_id, chunk_path.name, e, exc_info=True)
            finally:
                self.work_queue.task_done()
        logger.debug("Worker %d exited.", worker_id)

    def check_and_enforce_disk_limit(self) -> None:
        """Check total size of output directory and prune oldest completed chunks if over limit."""
        max_bytes = self.config.max_disk_gb * 1024 * 1024 * 1024
        current_size = self._get_directory_size(self.config.output_dir)

        if current_size <= max_bytes:
            return

        logger.warning(
            "Disk limit exceeded: %.2f GB used (cap is %.2f GB). Initiating pruning of oldest completed chunks...",
            current_size / (1024**3),
            self.config.max_disk_gb,
        )

        all_chunks = self.db.get_all_chunks()
        # Filter for chunks that have completed processing
        completed_chunks = [c for c in all_chunks if c.get("status") == "completed"]
        completed_chunks.sort(key=lambda c: float(c.get("created_at") or 0))

        for c in completed_chunks:
            p = Path(c["path"])
            if p.exists():
                try:
                    freed = p.stat().st_size
                    p.unlink()
                    current_size -= freed
                    logger.info("Pruned old chunk %s (freed %.1f MB)", p.name, freed / (1024 * 1024))
                except Exception as e:
                    logger.warning("Failed to delete chunk %s: %s", p.name, e)

            if current_size <= max_bytes:
                break

    def _get_directory_size(self, path: Path) -> int:
        """Compute recursive size of a directory in bytes."""
        total = 0
        if not path.exists():
            return 0
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
        return total

    def _parse_chunk_index(self, chunk_stem: str) -> int:
        """Extract numeric index from chunk stem (e.g. 'chunk_0003' -> 3)."""
        match = re.search(r"\d+", chunk_stem)
        return int(match.group(0)) if match else 0

    def is_overlapping_clip(self, global_start: float, global_end: float, title: str) -> bool:
        """Check if a clip's time-window overlaps >50% with an already-downloaded clip."""
        duration = max(0.1, global_end - global_start)
        with self._lock:
            for known_start, known_end, _ in self._known_windows:
                overlap_start = max(global_start, known_start)
                overlap_end = min(global_end, known_end)
                intersection = max(0.0, overlap_end - overlap_start)
                overlap_ratio = intersection / duration
                if overlap_ratio > 0.5:
                    return True
            return False

    def record_clip_window(self, global_start: float, global_end: float, title: str) -> None:
        """Record an extracted clip's time window for future deduplication checks."""
        with self._lock:
            self._known_windows.append((global_start, global_end, title))

    def process_chunk(self, chunk_path: Path) -> None:
        """Execute full OpenShorts processing lifecycle for a single chunk."""
        chunk_id = chunk_path.stem
        logger.info("=== Processing Chunk: %s ===", chunk_path.name)

        if not chunk_path.exists():
            logger.error("Chunk file does not exist: %s", chunk_path)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="failed")
            return

        # 1. Enforce disk guard before upload
        self.check_and_enforce_disk_limit()

        if self.config.dry_run:
            logger.info("[DRY RUN] Skipping OpenShorts upload & process for %s", chunk_path.name)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="completed")
            return

        # 2. Reserve upload slot
        try:
            slot_info = self.client.create_upload_slot(chunk_path.name)
            upload_id = slot_info["upload_id"]
            upload_url = slot_info["upload_url"]
        except OpenShortsClientError as e:
            logger.error("Failed to create upload slot for %s: %s", chunk_path.name, e)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="failed")
            return

        # 3. Stream upload video bytes
        try:
            self.client.stream_upload_file(upload_url, chunk_path)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="uploaded")
        except OpenShortsClientError as e:
            logger.error("Failed to stream upload %s: %s", chunk_path.name, e)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="failed")
            return

        # 4. Trigger OpenShorts process
        try:
            job_id = self.client.trigger_process(
                upload_id=upload_id,
                acknowledged=True,
                output_format="vertical",
            )
            self.db.upsert_job(job_id=job_id, chunk_id=chunk_id, status="queued")
        except OpenShortsClientError as e:
            logger.error("Failed to trigger process for %s (upload_id=%s): %s", chunk_path.name, upload_id, e)
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="failed")
            return

        # 5. Poll job status with exponential backoff
        result = self._wait_for_job(job_id)
        if not result:
            logger.error("Job %s failed or timed out.", job_id)
            self.db.upsert_job(job_id=job_id, chunk_id=chunk_id, status="failed")
            self.db.upsert_chunk(chunk_id, str(chunk_path), status="failed")
            return

        self.db.upsert_job(job_id=job_id, chunk_id=chunk_id, status="completed", result_json=result)
        self.db.upsert_chunk(chunk_id, str(chunk_path), status="completed")

        # 6. Parse clips, deduplicate, and download
        clips = result.get("clips") or []
        logger.info("OpenShorts returned %d clip(s) for job %s", len(clips), job_id)

        # Estimate chunk global start time using chunk index and segment overlap
        chunk_idx = self._parse_chunk_index(chunk_id)
        effective_chunk_time = max(1, self.config.chunk_seconds - self.config.overlap_seconds)
        chunk_global_offset = chunk_idx * effective_chunk_time

        for idx, clip in enumerate(clips):
            clip_title = clip.get("title") or clip.get("video_title_for_youtube_short") or f"Clip {idx + 1}"
            start_sec = float(clip.get("start") or clip.get("start_time") or 0.0)
            end_sec = float(clip.get("end") or clip.get("end_time") or (start_sec + 30.0))

            global_start = chunk_global_offset + start_sec
            global_end = chunk_global_offset + end_sec

            # Deduplication check across overlapping segment boundaries
            if self.is_overlapping_clip(global_start, global_end, clip_title):
                logger.info("Skipping clip #%d ('%s'): overlaps >50%% with existing clip.", idx + 1, clip_title)
                continue

            # Record window
            self.record_clip_window(global_start, global_end, clip_title)

            # Determine destination folder (review/ if manual approval required, shorts/ if auto_approve)
            target_folder = self.shorts_dir if self.config.auto_approve else self.review_dir
            filename = sanitize_filename(clip_title, chunk_id, idx + 1)
            dest_path = target_folder / filename

            clip_url = clip.get("download_url") or clip.get("video_url")
            if not clip_url:
                logger.warning("Clip #%d has no download_url or video_url; skipping.", idx + 1)
                continue

            try:
                self.client.download_clip(clip_url, dest_path)
                clip_uuid = str(uuid.uuid4())
                approved_flag = 1 if self.config.auto_approve else 0
                self.db.upsert_clip(
                    clip_id=clip_uuid,
                    job_id=job_id,
                    title=clip_title,
                    path=str(dest_path),
                    approved=approved_flag,
                )
                logger.info("Saved clip #%d to %s (approved=%d)", idx + 1, dest_path.name, approved_flag)
            except Exception as e:
                logger.error("Failed to download clip #%d (%s): %s", idx + 1, clip_url, e)

        # 7. Cleanup source chunk if requested
        if self.config.cleanup_chunks and chunk_path.exists():
            try:
                chunk_path.unlink()
                logger.info("Cleaned up source chunk: %s", chunk_path.name)
            except Exception as e:
                logger.warning("Could not delete source chunk %s: %s", chunk_path.name, e)

    def _wait_for_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Poll OpenShorts job status with exponential backoff until terminal state or timeout."""
        start_time = time.time()
        poll_interval = self.config.poll_initial_seconds
        seen_logs = 0

        logger.info("Waiting for job %s (timeout: %ss)...", job_id, self.config.job_timeout_seconds)

        while time.time() - start_time < self.config.job_timeout_seconds:
            if self.stop_event.is_set():
                logger.info("Stop requested while waiting for job %s", job_id)
                return None

            try:
                status_data = self.client.poll_status(job_id)
            except JobNotFoundError as e:
                logger.error("Job %s not found on server (purged or deleted): %s", job_id, e)
                return None
            except OpenShortsClientError as e:
                logger.warning("Failed status poll for %s: %s. Retrying in %.1fs...", job_id, e, poll_interval)
                time.sleep(poll_interval)
                poll_interval = min(poll_interval * 1.5, self.config.poll_max_seconds)
                continue

            status = status_data.get("status")
            logs = status_data.get("logs") or []

            # Log new messages from OpenShorts backend
            if len(logs) > seen_logs:
                for line in logs[seen_logs:]:
                    logger.info("  [OpenShorts %s] %s", job_id[:8], line)
                seen_logs = len(logs)

            if status == "completed":
                logger.info("Job %s completed successfully!", job_id)
                return status_data.get("result") or {}
            elif status == "failed":
                logger.error("Job %s reported failure.", job_id)
                return None

            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, self.config.poll_max_seconds)

        logger.error("Job %s timed out after %ds", job_id, self.config.job_timeout_seconds)
        return None

    def stop(self) -> None:
        """Signal workers to stop and wait for active processing tasks to conclude."""
        logger.info("Stopping ClipProcessor workers...")
        self.stop_event.set()
        self._executor.shutdown(wait=True)
        logger.info("ClipProcessor stopped.")
